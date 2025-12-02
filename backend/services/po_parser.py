import pdfplumber
import pandas as pd
import re
from typing import List, Dict, Any

def parse_po_to_order_data(pdf_path: str) -> tuple[List[pd.DataFrame], str, str]:
    """
    Returns: (List of DataFrames, Extracted PO Number, Extracted Ship Window)
    """
    all_dc_data: Dict[str, List[Dict]] = {}
    extracted_po_number = ""
    extracted_ship_window = "TBD"
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # 1. Text Extraction (Header Info)
            # 첫 페이지에서 PO 번호와 날짜 정보를 찾습니다.
            first_page_text = pdf.pages[0].extract_text()
            
            # PO Number Regex (다양한 패턴 대응)
            # 예: "PO #: 12345", "PO Number: 12345", "Purchase Order: 12345"
            po_match = re.search(r'(?:PO|Purchase Order)\s*#?[:.]?\s*(\d+)', first_page_text, re.IGNORECASE)
            if po_match:
                extracted_po_number = po_match.group(1)

            # Ship Window Regex (날짜 형식 찾기)
            # 예: "Ship Not Before: 11/20/2025", "Cancel After: 11/30/2025"
            # 단순화를 위해 텍스트 내의 날짜 패턴을 찾아 조합하거나, 특정 키워드 검색
            date_pattern = r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
            dates = re.findall(date_pattern, first_page_text)
            if len(dates) >= 2:
                extracted_ship_window = f"{dates[0]} - {dates[1]}"
            elif len(dates) == 1:
                extracted_ship_window = f"Start: {dates[0]}"

            # 2. Table Parsing
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2: continue
                    
                    header = table[0]
                    clean_header = [str(h).replace('\n', ' ') if h else '' for h in header]
                    
                    if len(clean_header) > 5:
                        if 'Vendor Style #' in clean_header[1] and 'Vendor Pack Size' in clean_header[5]:
                            dc_map = {} 
                            for idx, col_name in enumerate(clean_header):
                                match = re.search(r'DC#\s*(\d+)', col_name)
                                if match:
                                    dc_id = match.group(1)
                                    dc_map[idx] = dc_id
                                    if dc_id not in all_dc_data: all_dc_data[dc_id] = []
                        
                        for row in table[1:]:
                            if not row or not row[1]: continue
                            sku = row[1]
                            description = row[3] if len(row) > 3 else ""
                            
                            pack_size = 0
                            try:
                                if len(row) > 5 and row[5]: pack_size = int(row[5])
                            except: pass
                            if pack_size == 0:
                                try:
                                    if len(row) > 6 and row[6]: pack_size = int(row[6])
                                except: pass
                            
                            if pack_size == 0: continue
                                
                            for col_idx, dc_id in dc_map.items():
                                try:
                                    unit_qty_str = row[col_idx]
                                    if unit_qty_str:
                                        unit_qty_total = int(str(unit_qty_str).replace(',', ''))
                                        if unit_qty_total > 0:
                                            case_qty = unit_qty_total / pack_size
                                            all_dc_data[dc_id].append({
                                                'SKU': sku,
                                                'Description': description,
                                                'CaseQuantity': int(case_qty),
                                                'PackSize': pack_size,
                                                'UnitQuantity': unit_qty_total,
                                                'DC_ID': dc_id
                                            })
                                except: continue

    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return [], "", "Error"

    result_dfs = []
    sorted_dcs = sorted(all_dc_data.keys()) 
    for dc_id in sorted_dcs:
        data = all_dc_data.get(dc_id, [])
        df = pd.DataFrame(data, columns=['SKU', 'Description', 'CaseQuantity', 'PackSize', 'UnitQuantity', 'DC_ID'])
        result_dfs.append(df)
        
    return result_dfs, extracted_po_number, extracted_ship_window