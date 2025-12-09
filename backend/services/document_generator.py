import math
import pandas as pd
import os
from datetime import datetime

def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

class DocumentGenerator:
    def __init__(self, output_dir):
        self.output_dir = output_dir

    def generate_order_import(self, packing_list_df, dc_lookup, site_name, po_number, ship_window, unit_costs=None):
        """
        Order Import (QB) 엑셀 생성
        
        Args:
            packing_list_df: DataFrame with packing list data
            dc_lookup: DC information lookup dict
            site_name: Site name for the order
            po_number: PO number
            ship_window: Ship window string
            unit_costs: Optional dict mapping SKU to unit_cost (for Mother PO pricing)
        """
        import_rows = []
        
        # Build unit_cost lookup if not provided
        if unit_costs is None:
            unit_costs = {}
        
        for _, row in packing_list_df.iterrows():
            dc_id = str(row['DC #'])
            dc_info = dc_lookup.get(dc_id, {})
            sku = str(row.get('SKU', ''))
            
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

            # Get unit_cost for this SKU (>0 for Mother PO, 0 for DC PO)
            # Check row first, then fallback to unit_costs dict
            item_unit_cost = 0.0
            if 'unit_cost' in row and row['unit_cost']:
                item_unit_cost = float(row['unit_cost'])
            elif sku in unit_costs:
                item_unit_cost = float(unit_costs.get(sku, 0.0))

            import_rows.append({
                'Customer': customer,
                'trandate': datetime.now().strftime("%m/%d/%Y"),
                'otherrefnum': final_po_ref,
                'memo': f"Ship Window: {ship_window}", 
                'itemLine_item': sku,
                'itemLine_quantity': row['Qty (Cases)'],
                'itemLine_salesPrice': item_unit_cost,  # Map to unit_cost from parsed data
                'Site': site_name,
                'Sales Order #': sales_order_num,
                'Template': 'Sales Order Template'
            })
            
        df = pd.DataFrame(import_rows)
        filename = f"Order_Import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = os.path.join(self.output_dir, filename)
        df.to_excel(path, index=False)
        return f"/api/download/{filename}"

    def generate_review_worksheet(self, validated_items):
        """
        Generate extended CSV worksheet for PO review.
        
        Columns:
            DC_ID, Child_PO, SKU, Customer_Qty_Cases, Modified_Qty_Cases,
            Current_Stock_MAIN, Current_Stock_SUB, Status_Label, Memo_Action
        """
        rows = []
        for item in validated_items:
            po_qty = int(item.get('po_qty', 0))
            pack_size = int(item.get('pack_size', 1))
            if pack_size < 1:
                pack_size = 1
            default_case_qty = math.ceil(po_qty / pack_size)
            case_qty = int(item.get('case_qty', default_case_qty))

            rows.append({
                "DC_ID": str(item.get('dc_id', '')),
                "Child_PO": str(item.get('sales_order_num', item.get('po_number', ''))),
                "SKU": str(item.get('sku', '')),
                "Customer_Qty_Cases": case_qty,
                "Modified_Qty_Cases": "",
                "Current_Stock_MAIN": _safe_int(item.get('available_main_stock')),
                "Current_Stock_SUB": _safe_int(item.get('available_sub_stock')),
                "Status_Label": item.get('status_label', item.get('status', '')),
                "Memo_Action": item.get('memo_action', ''),
            })

        df = pd.DataFrame(rows)
        filename = f"Review_Worksheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = os.path.join(self.output_dir, filename)
        df.to_csv(path, index=False)
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
                    'Unit Qty': item.get('unit_qty', 0),
                    'unit_cost': item.get('unit_cost', 0.0),  # Include unit_cost for order import
                })
        
        df = pd.DataFrame(rows)
        filename = f"Packing_List_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = os.path.join(self.output_dir, filename)
        df.to_excel(path, index=False)
        return f"/api/download/{filename}", df
