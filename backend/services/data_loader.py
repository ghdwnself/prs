import pandas as pd
import os
import math
import logging
from services.firebase_service import firebase_manager
from core.config import settings
from firebase_admin import firestore

# 로깅 설정
logger = logging.getLogger(__name__)

class DataLoader:
    def __init__(self):
        self.data_dir = settings.DATA_DIR
        # 메모리 캐시 (Fallback용)
        # Renamed for clarity: products -> product_map, inventory -> inventory_map
        self.product_map = {}
        self.inventory_map = {}
        self.buyers = []
        
        # Legacy aliases for backward compatibility
        self.products = self.product_map
        self.inventory = self.inventory_map

    def _clean_nan(self, val, default):
        """NaN 값을 기본값으로 변환"""
        if pd.isna(val) or val == "" or val is None:
            return default
        return val
    
    def _safe_int(self, val, default=0):
        """안전한 정수 변환"""
        try:
            if pd.isna(val) or val == "" or val is None:
                return default
            return int(float(val))
        except (ValueError, TypeError):
            logger.warning(f"Invalid integer value: {val}, using default: {default}")
            return default

    def load_csv_to_memory(self):
        """서버 시작 시 CSV를 메모리에 로드 (DB 연결 실패 시 사용)"""
        logger.info("Loading CSV Data into Memory...")
        
        # Products
        p_path = os.path.join(self.data_dir, "products_template.csv")
        if os.path.exists(p_path):
            try:
                # Read CSV with first row as numeric headers, then map to proper names
                df = pd.read_csv(p_path, dtype={'1': str})
                
                # Column mapping (0-indexed position -> proper name)
                col_mapping = {
                    0: 'SKU',
                    2: 'ProductName_Short',
                    12: 'UnitsPerCase',  # Pack size column
                    13: 'CasePack',  # Alternative pack size
                    19: 'KeyAccountPrice_TJX',
                    14: 'MasterCarton_Length_inches',
                    15: 'MasterCarton_Width_inches',
                    16: 'MasterCarton_Height_inches',
                    23: 'Max_Cartons_per_Pallet',
                    24: 'Max_Height_inches'
                }
                
                for _, row in df.iterrows():
                    # Use column index 0 for SKU
                    sku = str(row.iloc[0]).strip() if len(row) > 0 else ''
                    if sku and sku.lower() not in ['nan', 'none', 'sku', '1']:
                        # Map numeric columns to proper names
                        mapped_row = {}
                        for col_idx, col_name in col_mapping.items():
                            if col_idx < len(row):
                                val = row.iloc[col_idx]
                                # Convert to proper type
                                if col_name in ['UnitsPerCase', 'CasePack', 'Max_Cartons_per_Pallet']:
                                    mapped_row[col_name] = self._safe_int(val, 1)
                                elif col_name in ['KeyAccountPrice_TJX', 'MasterCarton_Length_inches', 
                                                  'MasterCarton_Width_inches', 'MasterCarton_Height_inches', 
                                                  'Max_Height_inches']:
                                    try:
                                        mapped_row[col_name] = float(val) if pd.notna(val) else 0.0
                                    except:
                                        mapped_row[col_name] = 0.0
                                else:
                                    mapped_row[col_name] = val if pd.notna(val) else ''
                        
                        self.product_map[sku] = mapped_row
                logger.info(f"Products loaded: {len(self.product_map)}")
            except Exception as e:
                logger.error(f"Failed to load products CSV: {e}", exc_info=True)

        # Inventory - Now with location details preserved (MAIN vs SUB)
        i_path = os.path.join(self.data_dir, "inventory_template.csv")
        if os.path.exists(i_path):
            try:
                df = pd.read_csv(i_path, dtype={'sku': str})
                skipped_rows = 0
                for idx, row in df.iterrows():
                    try:
                        sku = str(row.get('sku', '')).strip()
                        if not sku or sku.lower() in ['nan', 'none', '']:
                            continue
                        
                        # Parse location: WH_MAIN -> MAIN, WH_SUB -> SUB
                        location_raw = str(row.get('location', 'MAIN')).strip().upper()
                        if not location_raw or location_raw.lower() in ['nan', 'none']:
                            location = 'MAIN'
                        elif 'SUB' in location_raw:
                            location = 'SUB'
                        elif 'MAIN' in location_raw:
                            location = 'MAIN'
                        else:
                            location = location_raw  # Fallback to raw value
                        
                        # 안전한 정수 변환 사용
                        on_hand = self._safe_int(row.get('onHand'), 0)
                        
                        if sku not in self.inventory_map:
                            self.inventory_map[sku] = {
                                "total": 0,
                                "locations": {}
                            }
                        
                        # Add to location-specific count
                        if location not in self.inventory_map[sku]["locations"]:
                            self.inventory_map[sku]["locations"][location] = 0
                        
                        self.inventory_map[sku]["locations"][location] += on_hand
                        self.inventory_map[sku]["total"] += on_hand
                    except Exception as row_error:
                        skipped_rows += 1
                        logger.warning(f"Skipped inventory row {idx}: {row_error}")
                        continue
                    
                logger.info(f"Inventory loaded: {len(self.inventory_map)} SKUs (skipped {skipped_rows} rows)")
            except Exception as e:
                logger.error(f"Failed to load inventory CSV: {e}")

        # Buyers
        b_path = os.path.join(self.data_dir, "SalesbyJames - db_buyer.csv")
        if os.path.exists(b_path):
            try:
                self.buyers = pd.read_csv(b_path).to_dict('records')
                logger.info(f"Buyers loaded: {len(self.buyers)}")
            except Exception as e:
                logger.error(f"Failed to load buyers CSV: {e}")

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