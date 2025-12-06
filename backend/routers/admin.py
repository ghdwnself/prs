from fastapi import APIRouter, HTTPException, Body
import os
import json
import glob
import logging
from datetime import datetime
from typing import Dict, Any

# Config & Services
from core.config import settings
from services.data_loader import data_loader
from services.firebase_service import firebase_manager

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# --- 경로 설정 (settings 기반) ---
HISTORY_DIR = os.path.join(settings.OUTPUT_DIR, "history")
CONFIG_FILE = os.path.join(settings.DATA_DIR, "system_config.json")

# --- 1. 시스템 설정 관리 (System Settings) ---

DEFAULT_CONFIG = {
    "safety_stock": 50,
    "pallet_max_height": 68,
    "pallet_max_weight": 2500,
    "pallet_base_weight": 40
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return DEFAULT_CONFIG

def save_config(config_data):
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)

@router.get("/settings")
async def get_settings():
    return {"status": "success", "data": load_config()}

@router.post("/settings")
async def update_settings(payload: Dict[str, Any] = Body(...)):
    try:
        current = load_config()
        # 값 업데이트 (숫자 변환)
        current['safety_stock'] = int(payload.get('safety_stock', current['safety_stock']))
        current['pallet_max_height'] = int(payload.get('pallet_max_height', current['pallet_max_height']))
        current['pallet_max_weight'] = int(payload.get('pallet_max_weight', current['pallet_max_weight']))
        current['pallet_base_weight'] = int(payload.get('pallet_base_weight', current['pallet_base_weight']))
        
        save_config(current)
        return {"status": "success", "message": "Settings updated successfully", "data": current}
    except Exception as e:
        raise HTTPException(500, f"Failed to save settings: {str(e)}")


# --- 2. PO 처리 이력 조회 (PO History) ---

@router.get("/history")
async def get_po_history():
    try:
        # outputs/history/**/*.json 파일 검색
        pattern = os.path.join(HISTORY_DIR, "**", "*.json")
        files = glob.glob(pattern, recursive=True)
        
        history_list = []
        for fpath in files:
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    meta = data.get('meta', {})
                    
                    # 파일명에서 날짜/시간 추출이 가능하지만 meta 정보 우선 사용
                    history_list.append({
                        "file_path": fpath, # 삭제 시 필요
                        "filename": os.path.basename(fpath),
                        "source": meta.get('source', 'Unknown'),
                        "customer": meta.get('customer', 'Unknown'),
                        "timestamp": meta.get('timestamp', ''),
                        # 결과 파일 링크 추정 (JSON 데이터 내부에 있거나, 파일명 규칙으로 유추)
                        # 여기서는 단순화를 위해 JSON 내부에 저장된 files 정보가 있다면 사용
                        "files": data.get('data', {}).get('files', {}) 
                    })
            except Exception as e:
                logger.warning(f"Failed to parse history file {fpath}: {e}")
                continue
        
        # 최신순 정렬
        history_list.sort(key=lambda x: x['timestamp'], reverse=True)
        return {"status": "success", "data": history_list}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.delete("/history")
async def delete_po_history(payload: Dict[str, str] = Body(...)):
    target_file = payload.get('file_path')
    try:
        if os.path.exists(target_file):
            os.remove(target_file)
            return {"status": "success", "message": "Record deleted"}
        else:
            raise HTTPException(404, "File not found")
    except Exception as e:
        raise HTTPException(500, str(e))


# --- 3. SKU 검사 도구 (Quick Check) ---

@router.get("/sku_check/{sku}")
async def check_sku(sku: str):
    """
    Check SKU details including inventory split by location (MAIN/SUB).
    """
    target_sku = str(sku).strip()
    
    # 기본 정보 (CSV 메모리) - Use product_map instead of products
    csv_info = data_loader.product_map.get(target_sku, {})
    
    # Get inventory from memory cache - Use inventory_map instead of inventory
    inv_info = data_loader.inventory_map.get(target_sku, {"total": 0, "locations": {}})
    
    result = {
        "sku": target_sku,
        "source": "Not Found",
        "desc": csv_info.get('ProductName_Short', '-'),
        "price": float(csv_info.get('KeyAccountPrice_TJX') or 0),
        "pack": int(csv_info.get('UnitsPerCase') or 1),
        "weight": float(csv_info.get('MasterCarton_Weight_lbs') or 0),
        "height": float(csv_info.get('MasterCarton_Height_inches') or 0),
        "stock": inv_info.get("total", 0),
        # New: Split inventory by location
        "stock_main": inv_info.get("locations", {}).get("MAIN", 0),
        "stock_sub": inv_info.get("locations", {}).get("SUB", 0),
        "locations": inv_info.get("locations", {}),
    }
    
    if csv_info:
        result["source"] = "CSV Memory"

    # Firebase 실시간 조회 (덮어쓰기)
    db = firebase_manager.get_db()
    if db:
        try:
            # Product
            doc = db.collection('products').document(target_sku).get()
            if doc.exists:
                d = doc.to_dict()
                result.update({
                    "source": "Firebase (Live)",
                    "desc": d.get('ProductName_Short', result['desc']),
                    "price": float(d.get('KeyAccountPrice_TJX') or result['price']),
                    "pack": int(d.get('UnitsPerCase') or result['pack']),
                    "weight": float(d.get('MasterCarton_Weight_lbs') or result['weight']),
                    "height": float(d.get('MasterCarton_Height_inches') or result['height']),
                })
            
            # Inventory with location split (MAIN vs SUB)
            locations = {}
            total_stock = 0
            docs = db.collection('inventory').where('sku', '==', target_sku).stream()
            for d in docs:
                doc_data = d.to_dict()
                on_hand = int(doc_data.get('onHand', 0))
                location = str(doc_data.get('location', 'MAIN')).strip().upper()
                
                if location not in locations:
                    locations[location] = 0
                locations[location] += on_hand
                total_stock += on_hand
            
            result['stock'] = total_stock
            result['stock_main'] = locations.get('MAIN', 0)
            result['stock_sub'] = locations.get('SUB', 0)
            result['locations'] = locations
            
        except Exception as e:
            result['error'] = str(e)
            
    return {"status": "success", "data": result}


# --- 4. 기존 데이터 동기화 (유지) ---

@router.get("/health/firebase")
async def check_firebase_health():
    return firebase_manager.check_health()

@router.post("/sync/products")
async def sync_products():
    return await data_loader.sync_products()

@router.post("/sync/inventory")
async def sync_inventory():
    return await data_loader.sync_inventory()