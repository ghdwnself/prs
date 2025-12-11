from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse, Response
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
from services.utils import safe_int, safe_float, sanitize_for_json

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
    Fetch inventory data with CACHE-FIRST strategy to minimize Firebase calls.
    Returns inventory map with MAIN/SUB split.
    """
    import time
    start_time = time.time()
    
    db = firebase_manager.get_db()
    inventory_map = {}
    
    logger.info(f"Fetching inventory for {len(sku_list)} SKUs (cache-first strategy)")
    cache_hits = 0
    firebase_calls = 0
    
    for sku in sku_list:
        sku = str(sku).strip()
        product_data = {'price': 0.0, 'pack_size': 1, 'weight': 15.0, 'height': 10.0, 'name': '', 'brand': ''}
        
        # 1. CACHE FIRST - Product Info
        cache_hit = False
        if sku in data_loader.product_map:
            try:
                cached = data_loader.product_map[sku]
                product_data['price'] = float(cached.get('KeyAccountPrice_TJX', 0.0) or 0.0)
                product_data['pack_size'] = safe_int(cached.get('UnitsPerCase', 1), 1)
                product_data['weight'] = float(cached.get('MasterCarton_Weight_lbs', 15.0) or 15.0)
                product_data['height'] = float(cached.get('MasterCarton_Height_inches', 10.0) or 10.0)
                product_data['name'] = cached.get('ProductName_Short', '')
                product_data['brand'] = cached.get('Brand', '')
                cache_hit = True
                cache_hits += 1
            except Exception as e:
                logger.warning(f"Failed to load cached product data for SKU {sku}: {e}")
        
        # Fallback to Firebase only if cache miss
        if not cache_hit and db:
            try:
                firebase_calls += 1
                prod_doc = db.collection('products').document(sku).get()
                if prod_doc.exists:
                    p = prod_doc.to_dict()
                    product_data['price'] = safe_float(p.get('KeyAccountPrice_TJX', 0.0), 0.0)
                    product_data['pack_size'] = safe_int(p.get('UnitsPerCase', 1), 1)
                    product_data['weight'] = safe_float(p.get('MasterCarton_Weight_lbs', 15.0), 15.0)
                    product_data['height'] = safe_float(p.get('MasterCarton_Height_inches', 10.0), 10.0)
                    product_data['name'] = p.get('ProductName_Short', '')
                    product_data['brand'] = p.get('Brand', '')
            except Exception as e:
                logger.warning(f"Failed to fetch product info from Firebase for SKU {sku}: {e}")

        # 2. CACHE FIRST - Inventory Stock with Location Details
        locations = {'MAIN': 0, 'SUB': 0}
        total_stock = 0
        
        # Try cache first
        if sku in data_loader.inventory_map:
            try:
                cached_inv = data_loader.inventory_map[sku]
                main_qty = safe_int(cached_inv.get('MAIN', 0), 0)
                sub_qty = safe_int(cached_inv.get('SUB', 0), 0)
                locations['MAIN'] = main_qty
                locations['SUB'] = sub_qty
                total_stock = main_qty + sub_qty
                cache_hits += 1
            except Exception as e:
                logger.warning(f"Failed to load cached inventory for SKU {sku}: {e}")
        
        # Fallback to Firebase only if cache miss
        if total_stock == 0 and db:
            try:
                firebase_calls += 1
                docs = db.collection('inventory').where('sku', '==', sku).stream()
                for doc in docs:
                    doc_data = doc.to_dict()
                    on_hand = safe_int(doc_data.get('onHand', 0), 0)
                    # Parse location: WH_MAIN -> MAIN, WH_SUB -> SUB
                    location_raw = str(doc_data.get('location', 'MAIN')).strip().upper()
                    if 'SUB' in location_raw:
                        location = 'SUB'
                    elif 'MAIN' in location_raw:
                        location = 'MAIN'
                    else:
                        location = location_raw
                    
                    if location not in locations:
                        locations[location] = 0
                    locations[location] += on_hand
                    total_stock += on_hand
            except Exception as e:
                logger.warning(f"Failed to fetch inventory from Firebase for SKU {sku}: {e}")

        inventory_map[sku] = {
            'total': total_stock,
            'locations': locations,
            **product_data
        }
    
    elapsed = time.time() - start_time
    logger.info(f"Inventory fetch completed: {elapsed:.2f}s (Cache hits: {cache_hits}/{len(sku_list)*2}, Firebase calls: {firebase_calls})")
    return inventory_map

# --- API Endpoints ---

@router.post("/download_review_worksheet")
async def download_review_worksheet(payload: Dict[str, Any] = Body(...)):
    """
    Generate and download Review Worksheet CSV for inventory adjustment.
    """
    try:
        validation = payload.get('validation', {})
        sku_details = validation.get('sku_details', [])
        po_meta = validation.get('po_meta', {})
        
        if not sku_details:
            raise HTTPException(400, "No SKU details found in validation data")
        
        # Create worksheet data
        worksheet_data = []
        for item in sku_details:
            worksheet_data.append({
                'SKU': item.get('sku', ''),
                'Brand': item.get('brand', ''),
                'Product_Name': item.get('name', ''),
                'Pack_Size': item.get('pack_size', 1),
                'System_Unit_Price': item.get('unit_price', 0),
                'PO_Unit_Price': item.get('po_unit_price', 0),
                'Mother_PO_Qty': item.get('mother_qty', 0),
                'DC_Total_Qty': item.get('dc_total_qty', 0),
                'Available_MAIN': item.get('inventory_modes', {}).get('main', {}).get('available', 0),
                'Available_SUB': item.get('inventory_modes', {}).get('sub', {}).get('available', 0),
                'Available_Total': item.get('inventory', {}).get('available_total', 0),
                'Shortage': item.get('inventory', {}).get('shortage', 0),
                'Status': item.get('status', ''),
                'Notes': ''
            })
        
        # Convert to DataFrame
        df = pd.DataFrame(worksheet_data)
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        po_number = po_meta.get('po_number', 'Unknown')
        safe_po = re.sub(r'[^\w\-]', '_', str(po_number))
        filename = f"Review_Worksheet_{safe_po}_{timestamp}.csv"
        filepath = os.path.join(settings.OUTPUT_DIR, filename)
        
        # Save CSV
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        logger.info(f"Generated review worksheet: {filename}")
        
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type='text/csv'
        )
        
    except Exception as e:
        logger.error(f"Failed to generate review worksheet: {e}")
        raise HTTPException(500, f"Failed to generate worksheet: {str(e)}")


@router.post("/validate_po_pair")
async def validate_po_pair(
    mother_file: UploadFile = File(...),
    dc_file: UploadFile = File(...)
):
    """
    Validate Mother PO against DC PO in a single request.
    Parses both PDFs, compares allocations, and validates inventory.
    """
    import time
    start_time = time.time()
    
    mother_temp_path = None
    dc_temp_path = None
    
    try:
        # Generate UUID-based temp filenames to avoid collisions
        # Sanitize filenames to prevent path traversal and invalid characters
        logger.info("=== Starting PO Validation ===")
        logger.info(f"Mother file: {mother_file.filename}, DC file: {dc_file.filename}")
        step_time = time.time()
        
        mother_safe_name = _sanitize_filename(mother_file.filename)
        dc_safe_name = _sanitize_filename(dc_file.filename)
        mother_temp_path = os.path.join(settings.TEMP_DIR, f"{uuid.uuid4()}_{mother_safe_name}")
        dc_temp_path = os.path.join(settings.TEMP_DIR, f"{uuid.uuid4()}_{dc_safe_name}")
        
        # Save uploaded files
        with open(mother_temp_path, "wb") as buffer:
            shutil.copyfileobj(mother_file.file, buffer)
        with open(dc_temp_path, "wb") as buffer:
            shutil.copyfileobj(dc_file.file, buffer)
        
        logger.info(f"File upload completed: {time.time() - step_time:.2f}s")
        step_time = time.time()
        
        # Parse Mother PO
        mother_items, mother_error = parse_po(mother_temp_path)
        if mother_error:
            raise HTTPException(400, f"Failed to parse Mother PO: {mother_error}")
        
        # Parse DC PO
        dc_items, dc_error = parse_po(dc_temp_path)
        if dc_error:
            raise HTTPException(400, f"Failed to parse DC PO: {dc_error}")
        
        logger.info(f"PDF parsing completed: {time.time() - step_time:.2f}s")
        step_time = time.time()
        
        # Extract PO numbers and ship windows
        mother_first = mother_items[0] if mother_items else {}
        dc_first = dc_items[0] if dc_items else {}
        mother_po_number = mother_first.get('po_number', '')
        dc_po_number = dc_first.get('po_number', '')
        mother_ship_window = mother_first.get('ship_window', 'TBD')
        vendor = dc_first.get('vendor', '')
        # Use buyer from DC PO (more accurate due to DC naming patterns)
        buyer = dc_first.get('buyer', '') or mother_first.get('buyer', '')
        
        # Build DC PO numbers: DC prefix + Mother PO number
        # DC items contain 'dc_po_prefix' from parsing (e.g., "10", "20", "30")
        dc_po_map = {}
        for item in dc_items:
            dc_id = str(item.get('dc_id', '')).strip()
            prefix = item.get('dc_po_prefix', '')
            if dc_id and prefix and dc_id not in dc_po_map:
                dc_po_map[dc_id] = f"{prefix}{mother_po_number}"
        
        dc_po_numbers = list(dc_po_map.values())
        if not dc_po_numbers:
            # Fallback to parsed PO number
            dc_po_numbers = list({str(item.get('po_number', '')).strip() for item in dc_items if item.get('po_number')})

        
        # Build Mother PO totals by SKU
        mother_totals = {}
        mother_unit_costs = {}  # Track unit cost from Mother PO
        for item in mother_items:
            sku = str(item.get('sku', '')).strip()
            qty = safe_int(item.get('po_qty', 0), 0)
            unit_cost_from_po = safe_float(item.get('unit_cost', 0.0), 0.0)
            mother_totals[sku] = mother_totals.get(sku, 0) + qty
            # Store unit cost from PO (if available and > 0)
            if unit_cost_from_po > 0 and sku not in mother_unit_costs:
                mother_unit_costs[sku] = unit_cost_from_po
        
        # Build DC PO totals by SKU
        dc_totals = {}
        dc_breakdown = {}
        for item in dc_items:
            sku = str(item.get('sku', '')).strip()
            dc_id = str(item.get('dc_id', '')).strip()
            qty = safe_int(item.get('po_qty', 0), 0)
            
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
        
        logger.info(f"PO comparison completed: {time.time() - step_time:.2f}s")
        step_time = time.time()
        
        # Fetch inventory data
        inv_map = get_inventory_data(all_skus)
        
        logger.info(f"Inventory data fetch: {time.time() - step_time:.2f}s")
        step_time = time.time()
        
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
            shortage = safe_int(item.get('remaining_shortage', 0), 0)
            if shortage > 0:
                inventory_warnings.append({
                    'sku': item.get('sku'),
                    'po_qty': safe_int(item.get('po_qty', 0), 0),
                    'available_stock': safe_int(item.get('available_stock', 0), 0),
                    'shortage': shortage,
                    'status': item.get('inventory_status', 'OK')
                })

        shortage_map: Dict[str, int] = {}
        for item in validated_mother:
            sku_key = str(item.get('sku', '')).strip()
            shortage_map[sku_key] = shortage_map.get(sku_key, 0) + safe_int(item.get('remaining_shortage', 0), 0)

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
            mother_qty = safe_int(mother_totals.get(sku, 0), 0)
            dc_qty = safe_int(dc_totals.get(sku, 0), 0)
            inv = inv_map.get(sku, {})
            
            # Get pack size from DC items first (more accurate), then fallback to product map
            pack_size = 1
            # Try to get pack_size from DC items (they have actual pack size from PDF table)
            for item in dc_items:
                if str(item.get('sku', '')).strip() == sku:
                    item_pack = safe_int(item.get('pack_size', 0), 0)
                    if item_pack > 1:
                        pack_size = item_pack
                        break
            
            # Fallback to product map if not found in DC items
            product_map = getattr(data_loader, "product_map", {})
            product_info = product_map.get(sku, {})
            if pack_size == 1:
                pack_size = safe_int(product_info.get('UnitsPerCase', product_info.get('CasePack', 1)), 1)
                if pack_size <= 0:
                    pack_size = 1
            
            # Get unit price - try multiple sources
            unit_price = safe_float(inv.get('price', 0.0), 0.0)
            if unit_price == 0 and product_info:
                # Fallback to product_map if inv doesn't have price
                unit_price = safe_float(product_info.get('KeyAccountPrice_TJX', 0.0), 0.0)
            
            logger.debug(f"SKU {sku}: price={unit_price}, pack={pack_size}")

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
                dc_qty_val = safe_int(dc_entry.get('qty', 0), 0)
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
            available_main = safe_int(locations.get('MAIN', 0), 0)
            available_sub = safe_int(locations.get('SUB', 0), 0)
            available_total = safe_int(inv.get('total', 0), 0)
            shortage_total = safe_int(shortage_map.get(sku, 0), 0)
            shortage_main = max(0, mother_qty - available_main)
            shortage_sub = max(0, mother_qty - available_sub)
            is_unregistered_sku = _is_unregistered_sku(inv, sku)
            
            # Compare PO price vs System price
            po_unit_price = mother_unit_costs.get(sku, 0.0)
            price_difference = 0.0
            price_match = True
            if po_unit_price > 0 and unit_price > 0:
                price_difference = unit_price - po_unit_price
                # Consider prices matching if within $0.01 (rounding tolerance)
                price_match = abs(price_difference) < 0.01

            sku_details.append({
                'sku': sku,
                'name': inv.get('name', ''),
                'brand': inv.get('brand', ''),
                'pack_size': pack_size,
                'unit_price': unit_price,
                'po_unit_price': po_unit_price,
                'price_difference': price_difference,
                'price_match': price_match,
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
        palletizer = Palletizer()
        
        for dc_id, totals_obj in by_dc_totals_map.items():
            sku_preview = heapq.nsmallest(SKU_PREVIEW_LIMIT, totals_obj['skus'])
            
            # Calculate pallets for this DC
            dc_pallet_items = []
            for item in dc_items:
                if str(item.get('dc_id', '')).strip() == dc_id:
                    sku = str(item.get('sku', '')).strip()
                    qty = safe_int(item.get('po_qty', 0), 0)
                    inv = inv_map.get(sku, {})
                    
                    # Get pack size
                    pack_size = safe_int(item.get('pack_size', 1), 1)
                    if pack_size < 1:
                        pack_size = 1
                    
                    # Get Max CT from product map (Max_Cartons_per_Pallet)
                    product_info = data_loader.product_map.get(sku, {})
                    max_ct = safe_int(product_info.get('Max_Cartons_per_Pallet', 20), 20)
                    if max_ct <= 0:
                        max_ct = 20
                    
                    dc_pallet_items.append({
                        'sku': sku,
                        'description': inv.get('name', ''),
                        'po_qty': qty,
                        'pack_size': pack_size,
                        'case_qty': math.ceil(qty / pack_size) if qty > 0 else 0,
                        'weight_lbs': inv.get('weight', 15.0),
                        'height_inches': inv.get('height', 10.0),
                        'max_cartons_per_pallet': max_ct
                    })
            
            # Calculate pallets
            dc_pallets = []
            if dc_pallet_items:
                try:
                    dc_pallets = palletizer.calculate_pallets(dc_pallet_items)
                    logger.info(f"DC #{dc_id}: Generated {len(dc_pallets)} pallets")
                except Exception as e:
                    logger.error(f"Failed to calculate pallets for DC #{dc_id}: {e}")
            
            by_dc_totals.append({
                'dc_id': dc_id,
                'units': totals_obj['units'],
                'cartons': totals_obj['cartons'],
                'skus': len(totals_obj['skus']),
                'sku_preview': sku_preview,
                'pallets': dc_pallets
            })
        
        total_qty_difference = totals['total_units_dc'] - totals['total_units_mother']
        total_qty_match = totals['total_units_dc'] == totals['total_units_mother']
        dc_po_number_list = [num for num in (dc_po_numbers if dc_po_numbers else ([dc_po_number] if dc_po_number else [])) if num]
        po_meta = {
            'po_number': mother_po_number or '',
            'dc_po_numbers': dc_po_number_list,
            'vendor': vendor or '',
            'buyer': buyer or '',
            'ship_window': mother_ship_window or 'TBD'
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
                'mother_po': mother_ship_window
            },
            'po_meta': po_meta,
            'sku_details': sku_details,
            'totals': totals,
            'by_dc_totals': by_dc_totals
        }
        
        logger.info(f"Building response data: {time.time() - step_time:.2f}s")
        
        # Store review record
        timestamp = datetime.now().isoformat()
        review_record = {
            'timestamp': timestamp,
            'mother_po': mother_po_number,
            'dc_po': dc_po_number,
            'po_meta': po_meta,
            'history_key': mother_po_number,
        }
        
        logger.info(f"Validation complete: {len(sku_details)} SKUs, {len(by_dc_totals)} DCs, {len(mismatches)} mismatches")
        logger.info(f"=== TOTAL TIME: {time.time() - start_time:.2f}s ===")
        logger.debug(f"by_dc_totals sample: {by_dc_totals[:2] if by_dc_totals else 'empty'}")
        
        # Sanitize validation result to remove NaN values before JSON serialization
        validation_result = sanitize_for_json(validation_result)
        review_record = sanitize_for_json(review_record)
        
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
        
        # Final sanitization before JSON response
        response_data = sanitize_for_json({
            "status": "success",
            "validation": validation_result
        })
        
        # JSON serialization with sanitization
        try:
            response_data = sanitize_for_json(response_data)
            json_str = json.dumps(response_data, ensure_ascii=False, allow_nan=False)
            return Response(content=json_str, media_type="application/json")
        except (ValueError, TypeError) as e:
            logger.error(f"JSON 직렬화 오류: {e}")
            raise HTTPException(500, f"데이터 변환 중 오류가 발생했습니다: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PO 검증 오류: {e}", exc_info=True)
        raise HTTPException(500, f"검증 처리 중 오류가 발생했습니다: {str(e)}")
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
        
        # Extract buyer from first parsed item
        buyer = parsed_items[0].get('buyer', 'UNKNOWN') if parsed_items else 'UNKNOWN'
        
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
            po_qty = safe_int(item.get('po_qty', 0), 0)
            pack_size = safe_int(item.get('pack_size', 1), 1)
            if pack_size < 1:
                pack_size = 1
            
            # Get price from inventory map
            inv = inv_map.get(sku, {'price': 0.0, 'pack_size': 1})
            price = safe_float(inv.get('price', 0.0), 0.0)
            case_qty = math.ceil(po_qty / pack_size)
            total_price = po_qty * price
            
            # Get inventory details
            main_stock = _get_stock_value(item, 'available_main_stock')
            sub_stock = _get_stock_value(item, 'available_sub_stock')
            total_stock = _get_stock_value(item, 'available_total_stock')
            remaining_shortage = safe_int(item.get('remaining_shortage', 0), 0)
            
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
                'Unit Cost': safe_float(item.get('unit_cost', 0.0), 0.0),
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
            "buyer": buyer,
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
            final_qty = safe_int(row.get('Final Qty (Units)', row.get('Final Qty', 0)), 0)
            if final_qty <= 0: continue
            
            inv = inv_map.get(sku, {'pack_size': 1, 'weight': 15, 'height': 10})
            pack_size = safe_int(row.get('Pack Size', inv.get('pack_size', 1)), 1)
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
    
    NOTE: This endpoint should be protected with authentication in production.
    Currently maintains consistency with other endpoints in the application
    which also lack authentication mechanisms.
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
