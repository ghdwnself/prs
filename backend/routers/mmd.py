from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse
import os
import shutil
import math
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Any

# Config & Services
from core.config import settings
from services.po_parser import parse_po_to_order_data
from services.palletizer import Palletizer
from services.document_generator import DocumentGenerator
from services.firebase_service import firebase_manager

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
def get_inventory_data(sku_list):
    db = firebase_manager.get_db()
    inventory_map = {}
    if not db: return inventory_map
    
    for sku in sku_list:
        product_data = {'price': 0.0, 'pack_size': 1, 'weight': 15.0, 'height': 10.0, 'name': ''}
        
        # 1. Product Info
        prod_doc = db.collection('products').document(sku).get()
        if prod_doc.exists:
            p = prod_doc.to_dict()
            product_data['price'] = float(p.get('KeyAccountPrice_TJX', 0.0) or 0.0)
            product_data['pack_size'] = int(p.get('UnitsPerCase', 1) or 1)
            product_data['weight'] = float(p.get('MasterCarton_Weight_lbs', 15.0) or 15.0)
            product_data['height'] = float(p.get('MasterCarton_Height_inches', 10.0) or 10.0)
            product_data['name'] = p.get('ProductName_Short', '')

        # 2. Inventory Stock (Sum)
        stock_sum = 0
        try:
            docs = db.collection('inventory').where('sku', '==', sku).stream()
            for doc in docs: stock_sum += int(doc.to_dict().get('onHand', 0))
        except Exception as e:
            logger.warning(f"Failed to fetch inventory for SKU {sku}: {e}")

        inventory_map[sku] = {'stock': stock_sum, **product_data}
    return inventory_map

# --- API Endpoints ---

@router.post("/analyze_po")
async def analyze_po(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(settings.TEMP_DIR, file.filename)
        with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        
        dc_dfs, po_num, ship_window = parse_po_to_order_data(file_path)
        
        all_skus = set()
        parsed_items = []
        for df in dc_dfs:
            if df.empty: continue
            dc_id = str(df['DC_ID'].iloc[0])
            for rec in df.to_dict('records'):
                sku = str(rec['SKU'])
                all_skus.add(sku)
                parsed_items.append({
                    'dc_id': dc_id, 'sku': sku, 'desc': rec.get('Description', ''),
                    'po_qty': int(rec.get('UnitQuantity', 0)),
                    'pdf_pack': int(rec.get('PackSize', 0))
                })
        
        inv_map = get_inventory_data(list(all_skus))
        analysis_result = []
        summary = {'total_skus': len(all_skus), 'total_units': 0, 'total_cartons': 0, 'total_amount': 0.0, 'shortage_skus_count': 0, 'dcs': {}}

        for item in parsed_items:
            sku = item['sku']
            inv = inv_map.get(sku, {'stock': 0, 'price': 0, 'pack_size': 1})
            
            pack_size = inv['pack_size'] if inv['pack_size'] > 1 else (item['pdf_pack'] if item['pdf_pack'] > 0 else 1)
            required = item['po_qty'] + 50 # Safety Stock
            shortage = max(0, required - inv['stock'])
            case_qty = math.ceil(item['po_qty'] / pack_size)
            total_price = item['po_qty'] * inv['price']
            
            analysis_result.append({
                'DC #': item['dc_id'], 'SKU': sku, 'Description': inv.get('name') or item['desc'],
                'PO Qty (Units)': item['po_qty'], 'Pack Size': pack_size,
                'Current Stock': inv['stock'], 'Shortage': shortage,
                'PO Price': inv['price'], 'Total Amount': total_price,
                'Final Qty (Units)': item['po_qty']
            })
            
            # Summary Logic
            summary['total_units'] += item['po_qty']
            summary['total_cartons'] += case_qty
            summary['total_amount'] += total_price
            if item['dc_id'] not in summary['dcs']:
                summary['dcs'][item['dc_id']] = {'units': 0, 'cartons': 0, 'amount': 0.0, 'shortage_items': []}
            
            dc_sum = summary['dcs'][item['dc_id']]
            dc_sum['units'] += item['po_qty']
            dc_sum['cartons'] += case_qty
            dc_sum['amount'] += total_price
            if shortage > 0:
                summary['shortage_skus_count'] += 1
                dc_sum['shortage_items'].append({'sku': sku, 'short': shortage})

        # Excel Creation
        df = pd.DataFrame(analysis_result)
        fname = f"Worksheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(os.path.join(settings.OUTPUT_DIR, fname), index=False)
        
        return JSONResponse({
            "status": "success", "summary": summary, "po_number": po_num, "ship_window": ship_window,
            "worksheet_url": f"/api/download/{fname}", "raw_data": analysis_result
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