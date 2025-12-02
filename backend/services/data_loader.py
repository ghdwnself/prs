import pandas as pd
import os
import math
from services.firebase_service import firebase_manager
from core.config import settings
from firebase_admin import firestore

class DataLoader:
    def __init__(self):
        self.data_dir = settings.DATA_DIR
        # 메모리 캐시 (Fallback용)
        self.products = {}
        self.inventory = {}
        self.buyers = []

    def _clean_nan(self, val, default):
        """NaN 값을 기본값으로 변환"""
        if pd.isna(val) or val == "" or val is None:
            return default
        return val

    def load_csv_to_memory(self):
        """서버 시작 시 CSV를 메모리에 로드 (DB 연결 실패 시 사용)"""
        print("🔄 Loading CSV Data into Memory...")
        
        # Products
        p_path = os.path.join(self.data_dir, "products_template.csv")
        if os.path.exists(p_path):
            try:
                df = pd.read_csv(p_path, dtype={'SKU': str})
                for _, row in df.iterrows():
                    sku = str(row.get('SKU', '')).strip()
                    if sku: self.products[sku] = row.to_dict()
                print(f"   ✅ Products loaded: {len(self.products)}")
            except: pass

        # Inventory
        i_path = os.path.join(self.data_dir, "inventory_template.csv")
        if os.path.exists(i_path):
            try:
                df = pd.read_csv(i_path, dtype={'sku': str})
                grouped = df.groupby('sku')['onHand'].sum()
                self.inventory = grouped.to_dict()
                print(f"   ✅ Inventory loaded: {len(self.inventory)}")
            except: pass

        # Buyers
        b_path = os.path.join(self.data_dir, "SalesbyJames - db_buyer.csv")
        if os.path.exists(b_path):
            try:
                self.buyers = pd.read_csv(b_path).to_dict('records')
                print(f"   ✅ Buyers loaded: {len(self.buyers)}")
            except: pass

    async def sync_products(self):
        """products_template.csv -> Firebase 'products' 컬렉션"""
        db = firebase_manager.get_db()
        if not db: return {"status": "error", "message": "Firebase Disconnected"}

        csv_path = os.path.join(self.data_dir, "products_template.csv")
        if not os.path.exists(csv_path):
            return {"status": "error", "message": "products_template.csv not found"}

        try:
            df = pd.read_csv(csv_path, dtype={'SKU': str})
            batch = db.batch()
            count = 0
            total = 0

            for _, row in df.iterrows():
                sku = str(row['SKU']).strip()
                if not sku: continue

                doc_ref = db.collection('products').document(sku)
                
                data = {
                    'ProductName_Short': self._clean_nan(row.get('ProductName_Short'), 'Unknown'),
                    'KeyAccountPrice_TJX': float(self._clean_nan(row.get('KeyAccountPrice_TJX'), 0.0)),
                    'UnitsPerCase': int(self._clean_nan(row.get('UnitsPerCase'), 1)),
                    'MasterCarton_Weight_lbs': float(self._clean_nan(row.get('MasterCarton_Weight_lbs'), 15.0)),
                    'MasterCarton_Height_inches': float(self._clean_nan(row.get('MasterCarton_Height_inches'), 10.0)),
                    'updated_at': firestore.SERVER_TIMESTAMP
                }
                
                batch.set(doc_ref, data, merge=True)
                count += 1
                
                if count >= 400:
                    batch.commit()
                    batch = db.batch()
                    total += count
                    count = 0
            
            if count > 0:
                batch.commit()
                total += count

            return {"status": "success", "message": f"Synced {total} products."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def sync_inventory(self):
        """inventory_template.csv -> Firebase 'inventory' 컬렉션"""
        db = firebase_manager.get_db()
        if not db: return {"status": "error", "message": "Firebase Disconnected"}

        csv_path = os.path.join(self.data_dir, "inventory_template.csv")
        if not os.path.exists(csv_path):
            return {"status": "error", "message": "inventory_template.csv not found"}

        try:
            df = pd.read_csv(csv_path, dtype={'sku': str})
            batch = db.batch()
            count = 0
            total = 0

            for _, row in df.iterrows():
                doc_id = str(row.get('docId', '')).strip()
                if not doc_id: continue

                doc_ref = db.collection('inventory').document(doc_id)
                
                data = {
                    'sku': str(row.get('sku', '')),
                    'location': str(row.get('location', '')),
                    'onHand': int(self._clean_nan(row.get('onHand'), 0)),
                    'available': int(self._clean_nan(row.get('available'), 0)),
                    'updated_at': firestore.SERVER_TIMESTAMP
                }

                batch.set(doc_ref, data, merge=True)
                count += 1

                if count >= 400:
                    batch.commit()
                    batch = db.batch()
                    total += count
                    count = 0
            
            if count > 0:
                batch.commit()
                total += count

            return {"status": "success", "message": f"Synced {total} inventory records."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

data_loader = DataLoader()