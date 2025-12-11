import pandas as pd
import math
from core.config import settings

class Palletizer:
    def __init__(self, config=None):
        """
        Palletizer 초기화. 설정값은 system_config.json에서 로드.
        구글 스프레드시트 팔레타이징 로직 기반:
        - Max CT (Max Cartons per Pallet) 사용
        - 부피 기반 계산 (1/Max CT = 단위 부피)
        - First Fit Decreasing Bin Packing
        
        Args:
            config: Optional dict with pallet settings (for testing/override)
        """
        # Load from settings if config not provided
        if config is None:
            system_config = settings._load_system_config()
            config = system_config
        
        # Pallet dimensions (fixed)
        self.PALLET_WIDTH = 40
        self.PALLET_LENGTH = 48
        self.PALLET_BASE_HEIGHT = 6
        
        # Configurable constraints from system_config.json
        self.MAX_HEIGHT = int(config.get('pallet_max_height', 68))
        self.MAX_WEIGHT = int(config.get('pallet_max_weight', 2500))
        self.PALLET_BASE_WEIGHT = int(config.get('pallet_base_weight', 40))

    def calculate_pallets(self, order_items):
        """
        구글 스프레드시트 로직 기반 팔레타이징:
        1. Max CT를 사용하여 각 SKU의 부피 계산 (1 / Max CT)
        2. Full Pallet (부피 1.0) 먼저 생성
        3. 잔량은 First Fit Decreasing로 Mixed Pallet 생성
        
        order_items: List of dicts with:
            - sku: SKU 번호
            - po_qty: 주문 수량 (cartons)
            - pack_size: case pack
            - weight_lbs: 무게
            - height_inches: 높이
            - max_cartons_per_pallet: Max CT (optional, default=20)
        
        Returns: List of pallet dicts
        """
        pallets = []
        pallet_counter = 1
        splitted_items = []  # 부피 < 1.0인 잔량들
        
        # 1. Full Pallet 생성 및 잔량 수집
        for item in order_items:
            sku = str(item.get('sku', '')).strip()
            case_qty = item.get('case_qty', 0) or item.get('po_qty', 0)
            
            if case_qty <= 0:
                continue
            
            # Max CT: Product 데이터에서 가져오기, 없으면 20 기본값
            max_ct = item.get('max_cartons_per_pallet', 20)
            if not max_ct or max_ct <= 0:
                max_ct = 20
            
            unit_plt = 1.0 / max_ct  # 1 카튼당 팔레트 부피
            
            qty_left = case_qty
            
            # Full Pallet 생성 (부피 = 1.0)
            while qty_left > 0:
                total_plt = qty_left * unit_plt
                
                if total_plt >= 1.0:
                    # Full Pallet 생성
                    full_qty = int(math.floor(max_ct))
                    
                    pallets.append({
                        'name': f'Pallet #{pallet_counter}',
                        'pallet_number': pallet_counter,
                        'type': 'FULL',
                        'skus': [sku],
                        'items': [{
                            'sku': sku,
                            'qty': full_qty,
                            'description': item.get('description', ''),
                            'pack_size': item.get('pack_size', 1)
                        }],
                        'total_units': full_qty * item.get('pack_size', 1),
                        'total_cartons': full_qty,
                        'total_weight': full_qty * item.get('weight_lbs', 15.0) + self.PALLET_BASE_WEIGHT,
                        'total_height': item.get('height_inches', 10.0) * (full_qty / max_ct * 10) + self.PALLET_BASE_HEIGHT,
                        'utilization_percent': 100
                    })
                    pallet_counter += 1
                    qty_left -= full_qty
                else:
                    # 잔량 - splitted items에 추가
                    volume = total_plt
                    splitted_items.append({
                        'sku': sku,
                        'volume': volume,
                        'qty': qty_left,
                        'max_ct': max_ct,
                        'description': item.get('description', ''),
                        'pack_size': item.get('pack_size', 1),
                        'weight_lbs': item.get('weight_lbs', 15.0),
                        'height_inches': item.get('height_inches', 10.0)
                    })
                    qty_left = 0
        
        # 2. Mixed Pallet 생성 (First Fit Decreasing)
        # 큰 부피부터 정렬
        splitted_items.sort(key=lambda x: x['volume'], reverse=True)
        
        bin_list = []  # 각 bin = 하나의 mixed pallet
        
        for item in splitted_items:
            placed = False
            
            # 기존 bin에 넣을 수 있는지 확인
            for bin_obj in bin_list:
                if bin_obj['total_volume'] + item['volume'] <= 1.0:
                    bin_obj['items'].append(item)
                    bin_obj['total_volume'] += item['volume']
                    placed = True
                    break
            
            # 넣을 수 없으면 새 bin 생성
            if not placed:
                bin_list.append({
                    'items': [item],
                    'total_volume': item['volume']
                })
        
        # 3. Mixed Pallet을 최종 pallets 리스트에 추가
        for bin_obj in bin_list:
            pal_items = []
            total_cartons = 0
            total_units = 0
            total_weight = self.PALLET_BASE_WEIGHT
            max_height = 0
            skus = []
            
            for it in bin_obj['items']:
                pal_items.append({
                    'sku': it['sku'],
                    'qty': it['qty'],
                    'description': it['description'],
                    'pack_size': it['pack_size']
                })
                total_cartons += it['qty']
                total_units += it['qty'] * it['pack_size']
                total_weight += it['qty'] * it['weight_lbs']
                max_height = max(max_height, it['height_inches'])
                skus.append(it['sku'])
            
            utilization_pct = int(bin_obj['total_volume'] * 100)
            
            pallets.append({
                'name': f'Pallet #{pallet_counter}',
                'pallet_number': pallet_counter,
                'type': 'MIXED',
                'skus': skus,
                'items': pal_items,
                'total_units': total_units,
                'total_cartons': total_cartons,
                'total_weight': total_weight,
                'total_height': max_height + self.PALLET_BASE_HEIGHT,
                'utilization_percent': utilization_pct
            })
            pallet_counter += 1
        
        return pallets

    def generate_packing_list_data(self, pallets, dc_info_lookup):
        rows = []
        for p in pallets:
            dc_id = p['dc_id']
            dc_data = dc_info_lookup.get(dc_id, {})
            
            for item in p['items']:
                rows.append({
                    'Pallet ID': p['pallet_id'],
                    'Pallet Type': p['type'],
                    'DC #': dc_id,
                    'Ship To': dc_data.get('PL Ship to', ''),
                    'Address': dc_data.get('Address', ''),
                    'City/State': f"{dc_data.get('City', '')}, {dc_data.get('State', '')}",
                    'SKU': item['sku'],
                    'Description': item['desc'],
                    'Qty (Cases)': item['qty'],
                    'Unit Qty': item['qty'] * item.get('pack_size', 1) # Unit 환산
                })
        return pd.DataFrame(rows)