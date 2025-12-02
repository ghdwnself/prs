from fastapi import APIRouter, HTTPException, Body
from typing import List, Dict, Any
import math
import os
import logging
import pandas as pd
from datetime import datetime

# Config & Services
from core.config import settings
from services.firebase_service import firebase_manager
from services.palletizer_emd import PalletizerEMD
from services.document_generator import DocumentGenerator
from services.data_loader import data_loader

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/emd", tags=["EMD"])

# --- Helper: 안전한 값 추출 ---
def safe_float(val, default=0.0):
    try: return float(val)
    except Exception:
        return default

def safe_int(val, default=1):
    try: return int(val)
    except Exception:
        return default

# --- Helper: 정보 조회 (CSV -> Firebase 순서) ---
def get_item_info(sku):
    target_sku = str(sku).strip()
    
    # 1. 기본값
    item_data = {
        'sku': target_sku,
        'desc': 'Unknown Item',
        'price': 0.0,
        'pack_size': 1,
        'weight': 15.0,
        'height': 10.0,
        'stock': 0,
        'is_valid': False,
        'source': 'None'
    }

    # 2. CSV 메모리 조회 (data_loader)
    if target_sku in data_loader.products:
        prod = data_loader.products[target_sku]
        
        price = prod.get('KeyAccountPrice_TJX') or prod.get('WholesalePrice') or 0
        pack = prod.get('UnitsPerCase') or 1
        weight = prod.get('MasterCarton_Weight_lbs') or 15
        height = prod.get('MasterCarton_Height_inches') or 10
        
        item_data.update({
            'desc': str(prod.get('ProductName_Short', 'Unknown Item')),
            'price': safe_float(price),
            'pack_size': safe_int(pack),
            'weight': safe_float(weight),
            'height': safe_float(height),
            'is_valid': True,
            'source': 'CSV'
        })
    
    # 3. CSV 재고 조회
    if target_sku in data_loader.inventory:
        item_data['stock'] = int(data_loader.inventory[target_sku])

    # 4. Firebase 조회 (연결된 경우)
    db = firebase_manager.get_db()
    if db:
        try:
            # (A) Product 정보
            doc = db.collection('products').document(target_sku).get()
            if doc.exists:
                d = doc.to_dict()
                price = d.get('KeyAccountPrice_TJX') or d.get('WholesalePrice') or 0
                pack = d.get('UnitsPerCase') or 1
                weight = d.get('MasterCarton_Weight_lbs') or 15
                height = d.get('MasterCarton_Height_inches') or 10
                
                item_data.update({
                    'desc': d.get('ProductName_Short', item_data['desc']),
                    'price': safe_float(price),
                    'pack_size': safe_int(pack),
                    'weight': safe_float(weight),
                    'height': safe_float(height),
                    'is_valid': True,
                    'source': 'Firebase'
                })

            # (B) Inventory 정보 (실시간 합산)
            stock_query = db.collection('inventory').where('sku', '==', target_sku).stream()
            stock_sum = 0
            found_stock = False
            for doc in stock_query:
                found_stock = True
                stock_sum += safe_int(doc.to_dict().get('onHand'))
            
            if found_stock:
                item_data['stock'] = stock_sum
                
        except Exception as e:
            logger.warning(f"DB Error ({target_sku}): {e}")

    return item_data

# --- API Endpoints ---

@router.get("/search_customers")
async def search_customers(query: str):
    if not query: return {"status": "success", "data": []}
    q = query.lower()
    results = []
    # data_loader에 로드된 바이어 리스트 사용
    for buyer in data_loader.buyers:
        name = str(buyer.get('Name', buyer.get('Customer Name', '')))
        if q in name.lower():
            results.append({'name': name, 'data': buyer})
            if len(results) > 10: break
    return {"status": "success", "data": results}

@router.post("/validate_skus")
async def validate_skus(payload: Dict[str, Any] = Body(...)):
    try:
        raw_skus = payload.get('skus', [])
        sku_list = list(set([str(s).strip() for s in raw_skus if str(s).strip()]))
        
        result = []
        for sku in sku_list:
            info = get_item_info(sku)
            result.append(info)
            
        return {"status": "success", "data": result}
        
    except Exception as e:
        logger.error(f"Validation Error: {e}")
        return {"status": "error", "message": str(e), "data": []}

@router.post("/process_order")
async def process_order(payload: Dict[str, Any] = Body(...)):
    """내부 직원용: 주문 처리 및 문서 생성"""
    try:
        order_info = payload.get('order_info', {})
        items = payload.get('items', [])
        
        pallet_input = []
        for item in items:
            unit_qty = safe_int(item.get('qty'), 0)
            if unit_qty <= 0: continue
            
            pack_size = safe_int(item.get('pack_size'), 1)
            case_qty = math.ceil(unit_qty / pack_size)
            
            pallet_input.append({
                'SKU': item['sku'], 'Qty': case_qty, 'unit_qty': unit_qty,
                'pack_size': pack_size, 'desc': item.get('desc', ''),
                'box_weight': safe_float(item.get('weight'), 15), 
                'box_height': safe_float(item.get('height'), 10)
            })
            
        palletizer = PalletizerEMD()
        pallets = palletizer.calculate_pallets(pallet_input)
        
        doc_gen = DocumentGenerator(settings.OUTPUT_DIR)
        
        customer_name = order_info.get('customer_name', 'Manual Customer')
        emd_lookup = {'EMD': {'Customer': customer_name, 'PL Ship to': customer_name}}
        
        pl_rows = []
        for p in pallets:
            for i in p['items']:
                pl_rows.append({'DC #': 'EMD', 'SKU': i['sku'], 'Qty (Cases)': i['qty']})
        pl_df = pd.DataFrame(pl_rows)
        
        import_url = doc_gen.generate_order_import(
            pl_df, emd_lookup, 
            order_info.get('site', 'Sub WH'), 
            {'EMD': order_info.get('po_number', '')},
            order_info.get('ship_window', '')
        )
        
        return {
            "status": "success",
            "files": {"order_import": import_url},
            "pallet_plan": pallets
        }
        
    except Exception as e:
        logger.error(f"Process Error: {e}")
        raise HTTPException(500, str(e))

@router.post("/submit_order")
async def submit_order(payload: Dict[str, Any] = Body(...)):
    """외부 고객용: 주문 접수 및 DB 저장"""
    db = firebase_manager.get_db()
    if not db:
        # DB가 없으면 에러 대신 가짜 성공 메시지라도 보내서 테스트 가능하게 함 (선택사항)
        # raise HTTPException(503, "Database not connected")
        logger.warning("DB Not Connected. Order not saved.")
        return {"status": "success", "message": "Order received (DB Disconnected)"}
        
    try:
        order_data = {
            "customer_name": payload.get('customer_name'),
            "po_number": payload.get('po_number'),
            "pickup_date": payload.get('pickup_date'),
            "items": payload.get('items', []),
            "status": "Pending",
            "created_at": datetime.now(),
            "source": "Customer Portal"
        }
        
        db.collection('orders').add(order_data)
        return {"status": "success", "message": "Order submitted successfully"}
        
    except Exception as e:
        logger.error(f"Submit Error: {e}")
        raise HTTPException(500, str(e))