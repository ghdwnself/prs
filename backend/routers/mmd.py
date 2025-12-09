from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse
import os
import shutil
import math
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List

# Config & Services
from core.config import settings
from services.po_parser import parse_po, parse_po_to_order_data
from services.validator import validate_po_data, get_validation_summary
from services.palletizer import Palletizer
from services.document_generator import DocumentGenerator
from services.firebase_service import firebase_manager
from services.data_loader import data_loader

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["MMD"])

# DC 정보 로드 (캐싱)
DC_LOOKUP = {}
division_path = os.path.join(settings.DATA_DIR, "TJX_PO_Template-division_info.csv")
if os.path.exists(division_path):
    try:
        df = pd.read_csv(division_path, dtype={'DC#': str})
        for _, row in df.iterrows(): DC_LOOKUP[str(row['DC#']).strip()] = row.to_dict()
    except Exception as e:
        logger.error(f"Failed to load DC lookup CSV: {e}")

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
            qty = int(item.get('po_qty', 0))
            mother_totals[sku] = mother_totals.get(sku, 0) + qty
        
        # Build DC PO totals by SKU
        dc_totals = {}
        dc_breakdown = {}  # Track which DCs have which SKUs
        for item in dc_po_items:
            sku = str(item.get('sku', '')).strip()
            dc_id = str(item.get('dc_id', '')).strip()
            qty = int(item.get('po_qty', 0))
            
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


@router.post("/analyze_po")
async def analyze_po(file: UploadFile = File(...)):
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
        
        # Validate PO data using the new validator
        validated_items = validate_po_data(
            parsed_items,
            inventory_map=validator_inv_map,
            product_map=validator_prod_map,
            safety_stock=50  # TODO: Load from config
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
            'main_short_count': validation_summary['main_short_count'],
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
            main_stock = int(item.get('main_stock', 0))
            sub_stock = int(item.get('sub_stock', 0))
            total_stock = int(item.get('total_stock', 0))
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
        
        # Excel Creation
        df = pd.DataFrame(analysis_result)
        fname = f"Worksheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(os.path.join(settings.OUTPUT_DIR, fname), index=False)
        
        return JSONResponse({
            "status": "success",
            "summary": summary,
            "po_number": po_num,
            "ship_window": ship_window,
            "worksheet_url": f"/api/download/{fname}",
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