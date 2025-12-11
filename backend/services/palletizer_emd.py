import math
from core.config import settings

class PalletizerEMD:
    def __init__(self, config=None):
        """
        EMD Palletizer 초기화. 설정값은 system_config.json에서 로드.
        
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
        
        # Configurable constraint from system_config.json
        # EMD uses same max_height as MMD
        self.MAX_HEIGHT = int(config.get('pallet_max_height', 68))

    def calculate_pallets(self, order_items):
        """
        EMD용 단순 적재 로직 (DC 구분 없음)
        """
        # 모든 아이템을 하나의 리스트로 처리
        # 박스 사이즈 정보가 없으므로, 기본 부피/높이 가정하여 적재
        
        current_pallet = {
            'pallet_id': 'P001',
            'type': 'EMD_MIXED',
            'items': [],
            'current_height': self.PALLET_BASE_HEIGHT
        }
        pallets = [current_pallet]
        pallet_counter = 1

        for item in order_items:
            qty_to_pack = item['Qty'] # Case Qty
            box_height = item.get('box_height', 10) # 기본 10인치
            
            # 단순 로직: 한 층에 10박스(Ti=10)라고 가정하고 높이 계산
            # 정교한 3D 패킹은 박스 치수 데이터가 필수적이므로, 현재는 근사치 사용
            
            while qty_to_pack > 0:
                # 현재 팔레트에 더 넣을 수 있는지 확인 (높이 기준)
                # 박스 1개 추가 시 높이 증가분 = box_height / 10 (한 층에 10개니까)
                height_increment = box_height / 10.0
                
                if current_pallet['current_height'] + height_increment > self.MAX_HEIGHT:
                    # 새 팔레트 생성
                    pallet_counter += 1
                    current_pallet = {
                        'pallet_id': f'P{pallet_counter:03d}',
                        'type': 'EMD_MIXED',
                        'items': [],
                        'current_height': self.PALLET_BASE_HEIGHT
                    }
                    pallets.append(current_pallet)
                
                # 아이템 추가 (이미 있으면 수량 증가)
                existing = next((i for i in current_pallet['items'] if i['sku'] == item['SKU']), None)
                if existing:
                    existing['qty'] += 1
                else:
                    current_pallet['items'].append({
                        'sku': item['SKU'],
                        'qty': 1,
                        'desc': item['desc']
                    })
                
                current_pallet['current_height'] += height_increment
                qty_to_pack -= 1
                
        # 결과 정리 (총 수량 등 계산)
        for p in pallets:
            p['total_cases'] = sum(i['qty'] for i in p['items'])
            p['est_height'] = round(p['current_height'], 1)
            
        return pallets