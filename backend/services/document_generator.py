import pandas as pd
import os
from datetime import datetime

class DocumentGenerator:
    def __init__(self, output_dir):
        self.output_dir = output_dir

    def generate_order_import(self, packing_list_df, dc_lookup, site_name, po_number, ship_window):
        """
        Order Import (QB) 엑셀 생성
        """
        import_rows = []
        
        for _, row in packing_list_df.iterrows():
            dc_id = str(row['DC #'])
            dc_info = dc_lookup.get(dc_id, {})
            
            # Mapping Logic
            customer = dc_info.get('Customer', f"Unknown DC {dc_id}")
            
            # PO Number Logic
            # PDF에서 추출한 PO 번호가 있으면 사용, 없으면 공란
            # DC Prefix (예: SAN) 추출
            pl_ship_to = str(dc_info.get('PL Ship to', dc_id))
            prefix = pl_ship_to.split(':')[0].strip() if ':' in pl_ship_to else dc_id
            
            # otherrefnum: "PREFIX PO#" (예: SAN 123456)
            final_po_ref = f"{prefix} {po_number}" if po_number else f"{prefix} (No PO)"
            
            # Sales Order #: "SO-PREFIX-PO#"
            sales_order_num = f"SO-{prefix}-{po_number}" if po_number else f"SO-{prefix}-{datetime.now().strftime('%m%d')}"

            import_rows.append({
                'Customer': customer,
                'trandate': datetime.now().strftime("%m/%d/%Y"),
                'otherrefnum': final_po_ref,
                'memo': f"Ship Window: {ship_window}", 
                'itemLine_item': row['SKU'],
                'itemLine_quantity': row['Qty (Cases)'],
                'itemLine_salesPrice': 0, # 가격 정보는 별도 로직 필요 (현재는 0)
                'Site': site_name,
                'Sales Order #': sales_order_num,
                'Template': 'Sales Order Template'
            })
            
        df = pd.DataFrame(import_rows)
        filename = f"Order_Import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = os.path.join(self.output_dir, filename)
        df.to_excel(path, index=False)
        return f"/api/download/{filename}"

    def generate_packing_list(self, pallets, dc_lookup):
        """Packing List 엑셀 생성"""
        rows = []
        for p in pallets:
            dc_id = p['dc_id']
            dc_data = dc_lookup.get(dc_id, {})
            
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
                    'Unit Qty': item.get('unit_qty', 0)
                })
        
        df = pd.DataFrame(rows)
        filename = f"Packing_List_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = os.path.join(self.output_dir, filename)
        df.to_excel(path, index=False)
        return f"/api/download/{filename}", df