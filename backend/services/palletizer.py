import pandas as pd
import math

class Palletizer:
    def __init__(self):
        # --- [수정됨] 사용자 요구사항 반영 ---
        self.PALLET_WIDTH = 40
        self.PALLET_LENGTH = 48
        self.MAX_HEIGHT = 68      # 최대 높이 68인치
        self.MAX_WEIGHT = 2500    # 최대 무게 2500lb
        self.PALLET_BASE_HEIGHT = 6 # 나무 팔레트 높이
        self.PALLET_BASE_WEIGHT = 40 # 나무 팔레트 무게

    def calculate_pallets(self, order_items):
        """
        order_items: List of dicts (SKU, Qty(Cases), weight_per_case, height_per_case 등 포함)
        """
        # 1. DC별 그룹화
        dc_groups = {}
        for item in order_items:
            dc_id = str(item.get('dc_id', 'Unknown'))
            if dc_id not in dc_groups:
                dc_groups[dc_id] = []
            dc_groups[dc_id].append(item)

        all_pallets = []
        global_pallet_counter = 1

        for dc_id, items in dc_groups.items():
            # 혼적(Mixed)을 위한 대기열
            mixed_candidates = []

            # --- 2-1. Full Pallet 계산 ---
            for item in items:
                sku = item['SKU']
                case_qty = item['Qty'] # 박스 수량
                
                # 아이템 물성치 (없으면 기본값 가정)
                box_weight = float(item.get('box_weight', 15)) # 기본 15lb
                box_height = float(item.get('box_height', 10)) # 기본 10inch
                
                # Ti-Hi 계산 (바닥면적 기준 박스 개수)
                # 가정: 12x12 박스라고 치면 48x40 팔레트에 약 12개 들어감 (보수적 계산)
                ti = 10 
                
                # 높이 제한으로 Hi(단수) 계산
                available_height = self.MAX_HEIGHT - self.PALLET_BASE_HEIGHT
                max_layers_height = int(available_height / box_height)
                
                # 무게 제한으로 Hi 계산
                available_weight = self.MAX_WEIGHT - self.PALLET_BASE_WEIGHT
                max_cases_weight = int(available_weight / box_weight)
                
                # 최종 Full Pallet 당 박스 개수
                cases_per_layer = ti
                max_cases_per_pallet = min(max_layers_height * ti, max_cases_weight)
                
                if max_cases_per_pallet <= 0: max_cases_per_pallet = 1 # 예외처리

                # Full Pallet 개수 산출
                full_count = case_qty // max_cases_per_pallet
                remainder = case_qty % max_cases_per_pallet

                for _ in range(full_count):
                    all_pallets.append({
                        'pallet_id': f"P{global_pallet_counter:03d}",
                        'dc_id': dc_id,
                        'type': 'FULL',
                        'items': [{
                            'sku': sku, 
                            'qty': max_cases_per_pallet, 
                            'desc': item.get('desc', ''),
                            'unit_qty': item.get('unit_qty', 0) # 단순 표기용 (정확하지 않을 수 있음)
                        }],
                        'total_cases': max_cases_per_pallet,
                        'est_height': (max_cases_per_pallet / ti) * box_height + self.PALLET_BASE_HEIGHT,
                        'est_weight': (max_cases_per_pallet * box_weight) + self.PALLET_BASE_WEIGHT
                    })
                    global_pallet_counter += 1
                
                if remainder > 0:
                    mixed_candidates.append({
                        'sku': sku,
                        'qty': remainder,
                        'desc': item.get('desc', ''),
                        'box_weight': box_weight,
                        'box_height': box_height,
                        'pack_size': item.get('pack_size', 1)
                    })

            # --- 2-2. Mixed Pallet 계산 (물리적 제한 적용) ---
            current_mixed = []
            current_weight = self.PALLET_BASE_WEIGHT
            current_height = self.PALLET_BASE_HEIGHT
            # Mixed는 높이 계산이 복잡하므로, 누적 부피나 단순 적층으로 근사치 계산
            # 여기서는 "무게"와 "부피(높이 환산)" 중 먼저 차는 것을 기준으로 함
            
            for item in mixed_candidates:
                qty_to_pack = item['qty']
                box_w = item['box_weight']
                box_h = item['box_height']
                
                while qty_to_pack > 0:
                    # 하나 더 넣었을 때 제한 초과 여부 확인
                    # 높이는 정확한 적재 시뮬레이션 없이 어려우므로, 
                    # "박스 10개가 1층(Height 증가)"이라고 단순화하여 계산
                    
                    # 현재 팔레트에 담긴 총 박스 수
                    current_total_cases = sum(i['qty'] for i in current_mixed)
                    current_layers = (current_total_cases // 10) + 1
                    est_next_height = (current_layers * 12) + self.PALLET_BASE_HEIGHT # 평균 박스높이 12 가정
                    
                    est_next_weight = current_weight + box_w

                    if est_next_weight > self.MAX_WEIGHT or est_next_height > self.MAX_HEIGHT:
                        # 팔레트 마감
                        all_pallets.append({
                            'pallet_id': f"P{global_pallet_counter:03d}",
                            'dc_id': dc_id,
                            'type': 'MIXED',
                            'items': current_mixed,
                            'total_cases': sum(i['qty'] for i in current_mixed),
                            'est_height': est_next_height, # 근사치
                            'est_weight': current_weight
                        })
                        global_pallet_counter += 1
                        current_mixed = []
                        current_weight = self.PALLET_BASE_WEIGHT
                        current_height = self.PALLET_BASE_HEIGHT
                    
                    # 박스 담기
                    # 이미 같은 SKU가 있는지 확인
                    existing = next((i for i in current_mixed if i['sku'] == item['sku']), None)
                    if existing:
                        existing['qty'] += 1
                    else:
                        current_mixed.append({
                            'sku': item['sku'],
                            'qty': 1,
                            'desc': item['desc'],
                            'pack_size': item['pack_size']
                        })
                    
                    current_weight += box_w
                    qty_to_pack -= 1

            # 마지막 잔량 처리
            if current_mixed:
                all_pallets.append({
                    'pallet_id': f"P{global_pallet_counter:03d}",
                    'dc_id': dc_id,
                    'type': 'MIXED',
                    'items': current_mixed,
                    'total_cases': sum(i['qty'] for i in current_mixed),
                    'est_height': 50, # 잔량
                    'est_weight': current_weight
                })
                global_pallet_counter += 1

        return all_pallets

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