from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse
import os
import shutil
import math
import logging
import pandas as pd
import uuid
import json
import re
import heapq
from datetime import datetime
from typing import Dict, Any, List, Optional

# Config & Services
from core.config import settings
from services.po_parser import parse_po, parse_po_to_order_data
from services.validator import validate_po_data, get_validation_summary, resolve_safety_stock
from services.palletizer import Palletizer
from services.document_generator import DocumentGenerator
from services.firebase_service import firebase_manager
from services.data_loader import data_loader
from services.utils import safe_int

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["MMD"])

SKU_PREVIEW_LIMIT = 5

# DC 정보 로드 (캐싱)
DC_LOOKUP = {}
division_path = os.path.join(settings.DATA_DIR, "TJX_PO_Template-division_info.csv")
if os.path.exists(division_path):
    try:
        df = pd.read_csv(division_path, dtype={'DC#': str})
        for _, row in df.iterrows(): DC_LOOKUP[str(row['DC#']).strip()] = row.to_dict()
    except Exception as e:
        logger.error(f"Failed to load DC lookup CSV: {e}")

def _sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal and invalid characters.
    Keeps only alphanumeric, dots, hyphens, and underscores.
    """
    # Remove path components
    filename = os.path.basename(filename)
    # Remove invalid characters (keep alphanumeric, dots, hyphens, underscores)
    filename = re.sub(r'[^\w\-\.]', '_', filename)
    # Prevent hidden files
    if filename.startswith('.'):
        filename = '_' + filename
    return filename

def _get_stock_value(data: Dict[str, Any], primary_key: str) -> int:
    return safe_int(data.get(primary_key))


def _is_unregistered_sku(inv_data: Dict[str, Any], sku: str) -> bool:
    """
    Determine whether a SKU is unregistered in master data.

    Args:
        inv_data: Inventory data for the SKU.
        sku: SKU identifier string.

    Returns:
        True when no product name exists and the SKU is absent from product_map.
        Uses an empty dict fallback if product_map is not available on data_loader.
    """
    product_map = getattr(data_loader, "product_map", None) or {}
    return (inv_data.get('name', '') == '') and (sku not in product_map)


# --- Helper Functions ---
def get_inventory_data(sku_list: List[str]) -> Dict[str, Dict]:
    """
    Fetch inventory data from Firebase with location details.
    Returns inventory map with MAIN/SUB split.
    """
    db = firebase_manager.get_db()
    inventory_map = {}
    
    for sku in sku_list:
        sku = str(sku).strip()
        product_data = {'price': 0.0, 'pack_size': 1, 'weight': 15.0, 'height': 10.0, 'name': ''}
        
        # 1. Product Info
        if db:
            try:
                prod_doc = db.collection('products').document(sku).get()
                if prod_doc.exists:
                    p = prod_doc.to_dict()
                    product_data['price'] = float(p.get('KeyAccountPrice_TJX', 0.0) or 0.0)
                    product_data['pack_size'] = int(p.get('UnitsPerCase', 1) or 1)
                    product_data['weight'] = float(p.get('MasterCarton_Weight_lbs', 15.0) or 15.0)
                    product_data['height'] = float(p.get('MasterCarton_Height_inches', 10.0) or 10.0)
                    product_data['name'] = p.get('ProductName_Short', '')
            except Exception as e:
                logger.warning(f"Failed to fetch product info for SKU {sku}: {e}")
        
        # Fallback to memory cache if no Firebase data
        if not product_data['name'] and sku in data_loader.product_map:
            cached = data_loader.product_map[sku]
            product_data['price'] = float(cached.get('KeyAccountPrice_TJX', 0.0) or 0.0)
            product_data['pack_size'] = int(cached.get('UnitsPerCase', 1) or 1)
            product_data['weight'] = float(cached.get('MasterCarton_Weight_lbs', 15.0) or 15.0)
            product_data['height'] = float(cached.get('MasterCarton_Height_inches', 10.0) or 10.0)
            product_data['name'] = cached.get('ProductName_Short', '')

        # 2. Inventory Stock with Location Details (MAIN vs SUB)
        locations = {'MAIN': 0, 'SUB': 0}
        total_stock = 0
        
        if db:
            try:
                docs = db.collection('inventory').where('sku', '==', sku).stream()
                for doc in docs:
                    doc_data = doc.to_dict()
                    on_hand = int(doc_data.get('onHand', 0))
                    location = str(doc_data.get('location', 'MAIN')).strip().upper()
                    
                    if location not in locations:
                        locations[location] = 0
                    locations[location] += on_hand
                    total_stock += on_hand
            except Exception as e:
                logger.warning(f"Failed to fetch inventory for SKU {sku}: {e}")
        
        # Fallback to memory cache
        if total_stock == 0 and sku in data_loader.inventory_map:
            cached_inv = data_loader.inventory_map[sku]
            locations = cached_inv.get('locations', {'MAIN': 0, 'SUB': 0}).copy()
            total_stock = cached_inv.get('total', 0)

        inventory_map[sku] = {
            'total': total_stock,
            'locations': locations,
            **product_data
        }
    
    return inventory_map

# --- API Endpoints ---

@router.post("/validate_dc_allocation")
async def validate_dc_allocation(payload: Dict[str, Any] = Body(...)):
    """
    Validate DC PO allocations against Mother PO requirements.
    Checks that sum of DC allocations matches Mother PO's SKU-level total.
    """
    try:
        mother_po_items = payload.get('mother_po_items', [])
        dc_po_items = payload.get('dc_po_items', [])
        
        # Build Mother PO totals by SKU
        mother_totals = {}
        for item in mother_po_items:
            sku = str(item.get('sku', '')).strip()
            try:
                qty = int(item.get('po_qty', 0))
            except (ValueError, TypeError):
                logger.warning(f"Invalid po_qty for SKU {sku} in Mother PO, using 0")
                qty = 0
            mother_totals[sku] = mother_totals.get(sku, 0) + qty
        
        # Build DC PO totals by SKU
        dc_totals = {}
        dc_breakdown = {}  # Track which DCs have which SKUs
        for item in dc_po_items:
            sku = str(item.get('sku', '')).strip()
            dc_id = str(item.get('dc_id', '')).strip()
            try:
                qty = int(item.get('po_qty', 0))
            except (ValueError, TypeError):
                logger.warning(f"Invalid po_qty for SKU {sku} in DC PO, using 0")
                qty = 0
            
            dc_totals[sku] = dc_totals.get(sku, 0) + qty
            
            if sku not in dc_breakdown:
                dc_breakdown[sku] = []
            dc_breakdown[sku].append({'dc_id': dc_id, 'qty': qty})
        
        # Compare and find mismatches
        mismatches = []
        for sku, mother_qty in mother_totals.items():
            dc_qty = dc_totals.get(sku, 0)
            
            if dc_qty != mother_qty:
                mismatches.append({
                    'sku': sku,
                    'mother_qty': mother_qty,
                    'dc_total': dc_qty,
                    'difference': dc_qty - mother_qty,
                    'dc_breakdown': dc_breakdown.get(sku, []),
                    'status': 'over' if dc_qty > mother_qty else 'under'
                })
        
        # Check for SKUs in DC PO but not in Mother PO
        for sku in dc_totals:
            if sku not in mother_totals:
                mismatches.append({
                    'sku': sku,
                    'mother_qty': 0,
                    'dc_total': dc_totals[sku],
                    'difference': dc_totals[sku],
                    'dc_breakdown': dc_breakdown.get(sku, []),
                    'status': 'extra'
                })
        
        validation_result = {
            'is_valid': len(mismatches) == 0,
            'total_skus_mother': len(mother_totals),
            'total_skus_dc': len(dc_totals),
            'mismatches': mismatches,
            'summary': {
                'matching_skus': len(mother_totals) - len(mismatches),
                'mismatched_skus': len(mismatches)
            }
        }
        
        return JSONResponse({
            "status": "success",
            "validation": validation_result
        })
        
    except Exception as e:
        logger.error(f"Error validating DC allocation: {e}")
        raise HTTPException(500, str(e))


@router.post("/validate_po_pair")
async def validate_po_pair(
    mother_file: UploadFile = File(...),
    dc_file: UploadFile = File(...)
):
    """
    Validate Mother PO against DC PO in a single request.
    Parses both PDFs, compares allocations, and validates inventory.
    """
    mother_temp_path = None
    dc_temp_path = None
    
    try:
        # Generate UUID-based temp filenames to avoid collisions
        # Sanitize filenames to prevent path traversal and invalid characters
        mother_safe_name = _sanitize_filename(mother_file.filename)
        dc_safe_name = _sanitize_filename(dc_file.filename)
        mother_temp_path = os.path.join(settings.TEMP_DIR, f"{uuid.uuid4()}_{mother_safe_name}")
        dc_temp_path = os.path.join(settings.TEMP_DIR, f"{uuid.uuid4()}_{dc_safe_name}")
        
        # Save uploaded files
        with open(mother_temp_path, "wb") as buffer:
            shutil.copyfileobj(mother_file.file, buffer)
        with open(dc_temp_path, "wb") as buffer:
            shutil.copyfileobj(dc_file.file, buffer)
        
        # Parse Mother PO
        mother_items, mother_error = parse_po(mother_temp_path)
        if mother_error:
            raise HTTPException(400, f"Failed to parse Mother PO: {mother_error}")
        
        # Parse DC PO
        dc_items, dc_error = parse_po(dc_temp_path)
        if dc_error:
            raise HTTPException(400, f"Failed to parse DC PO: {dc_error}")
        
        # Extract PO numbers and ship windows
        mother_first = mother_items[0] if mother_items else {}
        dc_first = dc_items[0] if dc_items else {}
        mother_po_number = mother_first.get('po_number', '')
        dc_po_number = dc_first.get('po_number', '')
        mother_ship_window = mother_first.get('ship_window', 'TBD')
        dc_ship_window = dc_first.get('ship_window', 'TBD')
        vendor = mother_first.get('vendor', '')
        buyer = mother_first.get('buyer', '')
        dc_po_numbers = list({str(item.get('po_number', '')).strip() for item in dc_items if item.get('po_number')})
        
        # Build Mother PO totals by SKU
        mother_totals = {}
        for item in mother_items:
            sku = str(item.get('sku', '')).strip()
            qty = int(item.get('po_qty', 0))
            mother_totals[sku] = mother_totals.get(sku, 0) + qty
        
        # Build DC PO totals by SKU
        dc_totals = {}
        dc_breakdown = {}
        for item in dc_items:
            sku = str(item.get('sku', '')).strip()
            dc_id = str(item.get('dc_id', '')).strip()
            qty = int(item.get('po_qty', 0))
            
            dc_totals[sku] = dc_totals.get(sku, 0) + qty
            
            if sku not in dc_breakdown:
                dc_breakdown[sku] = []
            dc_breakdown[sku].append({'dc_id': dc_id, 'qty': qty})
        
        # Compare and find mismatches
        mismatches = []
        matching_count = 0
        over_allocated = 0
        under_allocated = 0
        extra_skus = 0
        
        for sku, mother_qty in mother_totals.items():
            dc_qty = dc_totals.get(sku, 0)
            
            if dc_qty != mother_qty:
                status = 'over' if dc_qty > mother_qty else 'under'
                if status == 'over':
                    over_allocated += 1
                else:
                    under_allocated += 1
                    
                mismatches.append({
                    'sku': sku,
                    'mother_qty': mother_qty,
                    'dc_total': dc_qty,
                    'difference': dc_qty - mother_qty,
                    'dc_breakdown': dc_breakdown.get(sku, []),
                    'status': status
                })
            else:
                matching_count += 1
        
        # Check for SKUs in DC PO but not in Mother PO
        for sku in dc_totals:
            if sku not in mother_totals:
                extra_skus += 1
                mismatches.append({
                    'sku': sku,
                    'mother_qty': 0,
                    'dc_total': dc_totals[sku],
                    'difference': dc_totals[sku],
                    'dc_breakdown': dc_breakdown.get(sku, []),
                    'status': 'extra'
                })
        
        # Get all unique SKUs for inventory validation
        all_skus = list(set(list(mother_totals.keys()) + list(dc_totals.keys())))
        
        # Fetch inventory data
        inv_map = get_inventory_data(all_skus)
        
        # Convert to validator format
        validator_inv_map = {}
        validator_prod_map = {}
        for sku, data in inv_map.items():
            validator_inv_map[sku] = {
                'total': data.get('total', 0),
                'locations': data.get('locations', {'MAIN': 0, 'SUB': 0})
            }
            validator_prod_map[sku] = {
                'KeyAccountPrice_TJX': data.get('price', 0.0)
            }
        
        # Validate inventory for Mother PO items
        validated_mother = validate_po_data(
            mother_items,
            inventory_map=validator_inv_map,
            product_map=validator_prod_map,
            safety_stock_value=resolve_safety_stock(None),
            stock_mode="TOTAL"
        )
        
        # Build inventory warnings
        inventory_warnings = []
        for item in validated_mother:
            shortage = int(item.get('remaining_shortage', 0))
            if shortage > 0:
                inventory_warnings.append({
                    'sku': item.get('sku'),
                    'po_qty': int(item.get('po_qty', 0)),
                    'available_stock': int(item.get('available_stock', 0)),
                    'shortage': shortage,
                    'status': item.get('inventory_status', 'OK')
                })

        shortage_map: Dict[str, int] = {}
        for item in validated_mother:
            sku_key = str(item.get('sku', '')).strip()
            shortage_map[sku_key] = shortage_map.get(sku_key, 0) + int(item.get('remaining_shortage', 0))

        sku_details: List[Dict[str, Any]] = []
        by_dc_totals_map: Dict[str, Dict[str, Any]] = {}
        totals = {
            'total_skus': len(all_skus),
            'total_units_mother': 0,
            'total_units_dc': 0,
            'total_cartons_mother': 0,
            'total_cartons_dc': 0
        }

        for sku in all_skus:
            mother_qty = int(mother_totals.get(sku, 0))
            dc_qty = int(dc_totals.get(sku, 0))
            inv = inv_map.get(sku, {})
            
            # Get pack size from products collection (CasePack or UnitsPerCase)
            product_map = getattr(data_loader, "product_map", {})
            product_info = product_map.get(sku, {})
            pack_size = int(product_info.get('UnitsPerCase', product_info.get('CasePack', 1)))
            if pack_size <= 0:
                pack_size = 1
            
            unit_price = float(inv.get('price', 0.0) or 0.0)

            mother_cartons = math.ceil(mother_qty / pack_size) if mother_qty > 0 else 0
            dc_cartons = math.ceil(dc_qty / pack_size) if dc_qty > 0 else 0

            difference = dc_qty - mother_qty
            if mother_qty == 0 and dc_qty > 0:
                status = 'extra'
            elif dc_qty > mother_qty:
                status = 'over'
            elif dc_qty < mother_qty:
                status = 'under'
            else:
                status = 'ok'

            breakdown_list = []
            for dc_entry in dc_breakdown.get(sku, []):
                dc_id_val = str(dc_entry.get('dc_id', '')).strip()
                dc_qty_val = int(dc_entry.get('qty', 0))
                cartons_val = math.ceil(dc_qty_val / pack_size) if dc_qty_val > 0 else 0
                breakdown_list.append({
                    'dc_id': dc_id_val,
                    'qty': dc_qty_val,
                    'cartons': cartons_val
                })

                if dc_id_val not in by_dc_totals_map:
                    by_dc_totals_map[dc_id_val] = {
                        'dc_id': dc_id_val,
                        'units': 0,
                        'cartons': 0,
                        'skus': set()
                    }
                dc_totals_obj = by_dc_totals_map[dc_id_val]
                dc_totals_obj['units'] += dc_qty_val
                dc_totals_obj['cartons'] += cartons_val
                dc_totals_obj['skus'].add(sku)

            totals['total_units_mother'] += mother_qty
            totals['total_units_dc'] += dc_qty
            totals['total_cartons_mother'] += mother_cartons
            totals['total_cartons_dc'] += dc_cartons
            
            locations = inv.get('locations', {})
            available_main = int(locations.get('MAIN', 0))
            available_sub = int(locations.get('SUB', 0))
            available_total = int(inv.get('total', 0))
            shortage_total = int(shortage_map.get(sku, 0))
            shortage_main = max(0, mother_qty - available_main)
            shortage_sub = max(0, mother_qty - available_sub)
            is_unregistered_sku = _is_unregistered_sku(inv, sku)

            sku_details.append({
                'sku': sku,
                'name': inv.get('name', ''),
                'pack_size': pack_size,
                'unit_price': unit_price,
                'mother_qty': mother_qty,
                'mother_cartons': mother_cartons,
                'dc_total_qty': dc_qty,
                'dc_total_cartons': dc_cartons,
                'difference': difference,
                'status': status,
                'dc_breakdown': breakdown_list,
                'inventory': {
                    'mode': 'COMBINED',
                    'available_total': available_total,
                    'available_main': available_main,
                    'available_sub': available_sub,
                    'shortage': shortage_total
                },
                'inventory_modes': {
                    'combined': {'available': available_total, 'shortage': shortage_total},
                    'main': {'available': available_main, 'shortage': shortage_main},
                    'sub': {'available': available_sub, 'shortage': shortage_sub}
                },
                'is_unregistered_sku': is_unregistered_sku
            })

        by_dc_totals: List[Dict[str, Any]] = []
        for dc_id, totals_obj in by_dc_totals_map.items():
            sku_preview = heapq.nsmallest(SKU_PREVIEW_LIMIT, totals_obj['skus'])
            by_dc_totals.append({
                'dc_id': dc_id,
                'units': totals_obj['units'],
                'cartons': totals_obj['cartons'],
                'skus': len(totals_obj['skus']),
                'sku_preview': sku_preview,
                'pallets': [{
                    'name': f"DC #{dc_id}",
                    'pallet_number': str(dc_id),
                    'skus': sku_preview,
                    'total_units': totals_obj['units'],
                    'total_cartons': totals_obj['cartons']
                }]
            })
        
        total_qty_difference = totals['total_units_dc'] - totals['total_units_mother']
        total_qty_match = totals['total_units_dc'] == totals['total_units_mother']
        dc_po_number_list = [num for num in (dc_po_numbers if dc_po_numbers else ([dc_po_number] if dc_po_number else [])) if num]
        po_meta = {
            'po_number': mother_po_number or '',
            'dc_po_numbers': dc_po_number_list,
            'vendor': vendor or '',
            'buyer': buyer or '',
            'ship_window': mother_ship_window or 'TBD',
            'dc_ship_window': dc_ship_window or 'TBD'
        }
        # Build validation result
        validation_result = {
            'is_valid': len(mismatches) == 0 and len(inventory_warnings) == 0 and total_qty_match,
            'total_match': {
                'qty_match': total_qty_match,
                'difference_units': total_qty_difference
            },
            'summary': {
                'matching_skus': matching_count,
                'mismatched_skus': len(mismatches),
                'over_allocated': over_allocated,
                'under_allocated': under_allocated,
                'extra_skus': extra_skus,
                'total_inventory_warnings': len(inventory_warnings)
            },
            'mismatches': mismatches,
            'inventory_warnings': inventory_warnings,
            'po_numbers': {
                'mother_po': mother_po_number,
                'dc_po': dc_po_number
            },
            'ship_windows': {
                'mother_po': mother_ship_window,
                'dc_po': dc_ship_window
            },
            'po_meta': po_meta,
            'sku_details': sku_details,
            'totals': totals,
            'by_dc_totals': by_dc_totals
        }
        
        # Store review record
        timestamp = datetime.now().isoformat()
        review_record = {
            'timestamp': timestamp,
            'mother_po': mother_po_number,
            'dc_po': dc_po_number,
            'po_meta': po_meta,
            'history_key': mother_po_number,
            'source': buyer or vendor,
            'customer_file': mother_po_number,
            'summary': validation_result['summary'],
            'mismatch_count': len(mismatches),
            'inventory_warning_count': len(inventory_warnings),
            'result_files': []
        }
        
        # Save review to outputs/po_reviews/
        reviews_dir = os.path.join(settings.OUTPUT_DIR, "po_reviews")
        os.makedirs(reviews_dir, exist_ok=True)
        # Sanitize PO numbers for use in filename
        safe_mother_po = re.sub(r'[^\w\-]', '_', str(mother_po_number))
        safe_dc_po = re.sub(r'[^\w\-]', '_', str(dc_po_number))
        review_filename = f"{timestamp.replace(':', '-')}_{safe_mother_po}_vs_{safe_dc_po}.json"
        review_path = os.path.join(reviews_dir, review_filename)
        
        with open(review_path, 'w', encoding='utf-8') as f:
            json.dump(review_record, f, indent=2)
        
        return JSONResponse({
            "status": "success",
            "validation": validation_result
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating PO pair: {e}")
        raise HTTPException(500, str(e))
    finally:
        # Clean up temp files
        if mother_temp_path and os.path.exists(mother_temp_path):
            try:
                os.remove(mother_temp_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {mother_temp_path}: {e}")
        if dc_temp_path and os.path.exists(dc_temp_path):
            try:
                os.remove(dc_temp_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {dc_temp_path}: {e}")


@router.post("/analyze_po")
async def analyze_po(
    file: UploadFile = File(...),
    stock_mode: str = "TOTAL",
    safety_stock_value: Optional[int] = None
):
    """
    Analyze PO PDF file using new dynamic parser and validator.
    Returns validated items with MAIN/SUB inventory status.
    """
    try:
        file_path = os.path.join(settings.TEMP_DIR, file.filename)
        with open(file_path, "wb") as buffer: 
            shutil.copyfileobj(file.file, buffer)
        
        # Use the new parser that returns List[Dict]
        parsed_items, po_num, ship_window = parse_po_to_order_data(file_path)
        
        # Check for parsing errors
        if not parsed_items:
            return JSONResponse({
                "status": "error",
                "message": "No valid data found in PO PDF",
                "po_number": po_num,
                "ship_window": ship_window
            }, status_code=400)
        
        # Extract all SKUs for inventory lookup
        all_skus = list(set(str(item.get('sku', '')).strip() for item in parsed_items))
        
        # Fetch inventory data with MAIN/SUB split
        inv_map = get_inventory_data(all_skus)
        
        # Convert inv_map to format expected by validator
        validator_inv_map = {}
        for sku, data in inv_map.items():
            validator_inv_map[sku] = {
                'total': data.get('total', 0),
                'locations': data.get('locations', {'MAIN': 0, 'SUB': 0})
            }
        
        # Build product_map for validator
        validator_prod_map = {}
        for sku, data in inv_map.items():
            validator_prod_map[sku] = {
                'KeyAccountPrice_TJX': data.get('price', 0.0)
            }
        
        # Determine safety stock (configurable, defaults to settings)
        effective_safety_stock = resolve_safety_stock(safety_stock_value)

        # Validate PO data using the new validator
        validated_items = validate_po_data(
            parsed_items,
            inventory_map=validator_inv_map,
            product_map=validator_prod_map,
            safety_stock_value=effective_safety_stock,
            stock_mode=stock_mode
        )
        
        # Get validation summary
        validation_summary = get_validation_summary(validated_items)
        
        # Build analysis result for frontend/Excel (backward compatible format)
        analysis_result = []
        summary = {
            'total_skus': len(all_skus),
            'total_units': 0,
            'total_cartons': 0,
            'total_amount': 0.0,
            'shortage_skus_count': 0,
            'ok_count': validation_summary['ok_count'],
            'inventory_low_count': validation_summary['inventory_low_count'],
            'out_of_stock_count': validation_summary['out_of_stock_count'],
            'dcs': {}
        }
        
        for item in validated_items:
            sku = str(item.get('sku', '')).strip()
            dc_id = str(item.get('dc_id', '')) or 'N/A'
            po_qty = int(item.get('po_qty', 0))
            pack_size = int(item.get('pack_size', 1))
            if pack_size < 1:
                pack_size = 1
            
            # Get price from inventory map
            inv = inv_map.get(sku, {'price': 0.0, 'pack_size': 1})
            price = float(inv.get('price', 0.0))
            case_qty = math.ceil(po_qty / pack_size)
            total_price = po_qty * price
            
            # Get inventory details
            main_stock = _get_stock_value(item, 'available_main_stock')
            sub_stock = _get_stock_value(item, 'available_sub_stock')
            total_stock = _get_stock_value(item, 'available_total_stock')
            remaining_shortage = int(item.get('remaining_shortage', 0))
            
            analysis_result.append({
                'DC #': dc_id,
                'SKU': sku,
                'Description': str(item.get('description', '')),
                'PO Qty (Units)': po_qty,
                'Pack Size': pack_size,
                'Main Stock': main_stock,
                'Sub Stock': sub_stock,
                'Total Stock': total_stock,
                'Shortage': remaining_shortage,
                'Status': item.get('status', 'OK'),
                'Status Label': item.get('status_label', item.get('status', '')),
                'PO Price': price,
                'Unit Cost': float(item.get('unit_cost', 0.0)),
                'Total Amount': total_price,
                'Final Qty (Units)': po_qty,
                'Sales Order #': item.get('sales_order_num', ''),
                'Price Warning': item.get('price_warning', ''),
            })
            
            # Summary Logic
            summary['total_units'] += po_qty
            summary['total_cartons'] += case_qty
            summary['total_amount'] += total_price
            
            if dc_id not in summary['dcs']:
                summary['dcs'][dc_id] = {
                    'units': 0,
                    'cartons': 0,
                    'amount': 0.0,
                    'shortage_items': []
                }
            
            dc_sum = summary['dcs'][dc_id]
            dc_sum['units'] += po_qty
            dc_sum['cartons'] += case_qty
            dc_sum['amount'] += total_price
            
            if remaining_shortage > 0:
                summary['shortage_skus_count'] += 1
                dc_sum['shortage_items'].append({
                    'sku': sku,
                    'short': remaining_shortage
                })
        
        doc_gen = DocumentGenerator(settings.OUTPUT_DIR)
        worksheet_url = doc_gen.generate_review_worksheet(validated_items)
        
        return JSONResponse({
            "status": "success",
            "summary": summary,
            "po_number": po_num,
            "ship_window": ship_window,
            "worksheet_url": worksheet_url,
            "raw_data": analysis_result
        })
    except Exception as e:
        logger.error(f"Error analyzing PO: {e}")
        raise HTTPException(500, str(e))

@router.post("/calculate_pallets")
async def calculate_pallets(payload: Dict[str, Any] = Body(...)):
    try:
        source_type = payload.get('source_type')
        site_name = payload.get('site', 'Sub WH')
        po_number = payload.get('po_number', '')
        ship_window = payload.get('ship_window', 'TBD')
        
        data_rows = []
        if source_type == 'excel':
            file_path = os.path.join(settings.TEMP_DIR, payload.get('filename'))
            data_rows = pd.read_excel(file_path).to_dict('records')
        else:
            data_rows = payload.get('data', [])

        # Re-fetch inventory for weights
        skus = list(set(str(r.get('SKU', '')) for r in data_rows))
        inv_map = get_inventory_data(skus)
        
        pallet_input = []
        for row in data_rows:
            sku = str(row.get('SKU', ''))
            final_qty = int(row.get('Final Qty (Units)', row.get('Final Qty', 0)))
            if final_qty <= 0: continue
            
            inv = inv_map.get(sku, {'pack_size': 1, 'weight': 15, 'height': 10})
            pack_size = int(row.get('Pack Size', inv['pack_size']))
            if pack_size < 1: pack_size = 1
            
            pallet_input.append({
                'SKU': sku, 'Qty': math.ceil(final_qty / pack_size), 'unit_qty': final_qty,
                'pack_size': pack_size, 'dc_id': str(row.get('DC #', '')),
                'desc': str(row.get('Description', '')),
                'box_weight': inv['weight'], 'box_height': inv['height']
            })

        palletizer = Palletizer()
        pallets = palletizer.calculate_pallets(pallet_input)
        
        doc_gen = DocumentGenerator(settings.OUTPUT_DIR)
        pl_url, pl_df = doc_gen.generate_packing_list(pallets, DC_LOOKUP)
        import_url = doc_gen.generate_order_import(pl_df, DC_LOOKUP, site_name, po_number, ship_window)
        
        return JSONResponse({
            "status": "success",
            "files": {"order_import": import_url}, # Packing list hidden as requested
            "pallet_plan": pallets
        })
    except Exception as e:
        logger.error(f"Error calculating pallets: {e}")
        raise HTTPException(500, str(e))

@router.post("/upload_temp_excel")
async def upload_temp_excel(file: UploadFile = File(...)):
    try:
        path = os.path.join(settings.TEMP_DIR, file.filename)
        with open(path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "filename": file.filename}
    except Exception as e: raise HTTPException(500, str(e))


@router.get("/po_reviews")
async def get_po_reviews(limit: int = 10):
    """
    Get list of recent PO review records.
    Returns reviews sorted by timestamp descending with optional limit.
    """
    try:
        reviews_dir = os.path.join(settings.OUTPUT_DIR, "po_reviews")
        
        if not os.path.exists(reviews_dir):
            return JSONResponse({
                "status": "success",
                "data": []
            })
        
        # List all JSON files in reviews directory
        review_files = []
        for filename in os.listdir(reviews_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(reviews_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        review_data = json.load(f)
                        review_files.append(review_data)
                except Exception as e:
                    logger.warning(f"Failed to read review file {filename}: {e}")
                    continue
        
        # Sort by timestamp descending
        review_files.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Apply limit
        limited_reviews = review_files[:limit] if limit > 0 else review_files
        
        return JSONResponse({
            "status": "success",
            "data": limited_reviews
        })
        
    except Exception as e:
        logger.error(f"Error retrieving PO reviews: {e}")
        raise HTTPException(500, str(e))


@router.delete("/delete_reviews")
async def delete_reviews():
    """
    Delete all PO review records from the po_reviews directory.
    """
    try:
        reviews_dir = os.path.join(settings.OUTPUT_DIR, "po_reviews")
        if os.path.exists(reviews_dir):
            shutil.rmtree(reviews_dir)
            os.makedirs(reviews_dir, exist_ok=True)
        return JSONResponse({"status": "success", "message": "모든 검증 기록이 삭제되었습니다."})
    except Exception as e:
        logger.error(f"Error deleting reviews: {e}")
        return JSONResponse({"status": "error", "message": str(e)})
