import pdfplumber
import re
import math
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

# 로깅 설정
logger = logging.getLogger(__name__)

# TJX Brand Prefixes for SalesOrder# generation
TJX_BRAND_PREFIXES = {
    'TJ MAXX': 'TJM',
    'TJMAXX': 'TJM',
    'MARSHALLS': 'MAR',
    'HOMEGOODS': 'HGD',
    'HOMESENSE': 'HSE',
    'WINNERS': 'WIN',
}

def _get_brand_prefix(text: str) -> str:
    """Extract brand prefix from PO text for TJX brands."""
    text_upper = text.upper()
    for brand, prefix in TJX_BRAND_PREFIXES.items():
        if brand in text_upper:
            return prefix
    return 'MMD'  # Default prefix

def _find_column_index(headers: List[str], patterns: List[str]) -> int:
    """Find column index by matching any of the given patterns."""
    for idx, header in enumerate(headers):
        header_clean = str(header).strip().upper() if header else ''
        for pattern in patterns:
            if re.search(pattern, header_clean, re.IGNORECASE):
                return idx
    return -1

def _find_dc_columns(headers: List[str]) -> Dict[int, str]:
    """Find DC columns dynamically using regex patterns."""
    dc_map = {}
    for idx, header in enumerate(headers):
        if not header:
            continue
        header_str = str(header).replace('\n', ' ')
        # Pattern: DC#123, DC# 123, DC #123, DC # 123, etc.
        match = re.search(r'DC\s*#?\s*(\d+)', header_str, re.IGNORECASE)
        if match:
            dc_id = match.group(1)
            dc_map[idx] = dc_id
    return dc_map

def _extract_po_prefix_map(text: str) -> Dict[str, str]:
    """
    Extract PO prefix mapping from page 1.
    Pattern: "PO #12345 ... DC #789" maps DC 789 to prefix extracted from PO context.
    Returns: {dc_id: prefix}
    """
    prefix_map = {}
    # Look for patterns like: "PO #12345678 DC #0789" or similar
    pattern = r'PO\s*#?\s*(\d+).*?DC\s*#?\s*(\d+)'
    matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
    
    for po_num, dc_id in matches:
        # First few digits of PO can be used as prefix
        prefix = po_num[:3] if len(po_num) >= 3 else po_num
        prefix_map[dc_id] = prefix
    
    return prefix_map

def parse_po(pdf_path: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Dynamic PO parsing for TJX brands (TJ Maxx/Marshalls/HomeGoods).
    
    Returns: (List of parsed item dicts, error_message or None)
    
    Output dict structure:
    {
        'sku': str,
        'description': str,
        'po_qty': int,           # Total quantity from PO
        'pack_size': int,
        'case_qty': int,
        'unit_cost': float,      # 0 for DC POs, >0 for Mother POs
        'dc_id': str,            # DC identifier
        'sales_order_num': str,  # Generated SalesOrder#
        'po_number': str,        # Original PO number
        'ship_window': str,
        'is_mother_po': bool,    # True if Mother PO (no DC columns)
    }
    """
    parsed_items: List[Dict[str, Any]] = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return [], "PDF has no pages"
            
            # 1. Page 1 Analysis - Extract PO Number, Ship Window, Brand
            first_page_text = pdf.pages[0].extract_text() or ""
            
            # Extract PO Number
            extracted_po_number = ""
            po_match = re.search(r'(?:PO|Purchase Order)\s*#?[:.]?\s*(\d+)', first_page_text, re.IGNORECASE)
            if po_match:
                extracted_po_number = po_match.group(1)
            
            # Extract Ship Window
            extracted_ship_window = "TBD"
            date_pattern = r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
            dates = re.findall(date_pattern, first_page_text)
            if len(dates) >= 2:
                extracted_ship_window = f"{dates[0]} - {dates[1]}"
            elif len(dates) == 1:
                extracted_ship_window = f"Start: {dates[0]}"
            
            # Get brand prefix
            brand_prefix = _get_brand_prefix(first_page_text)
            
            # Get DC prefix mapping
            dc_prefix_map = _extract_po_prefix_map(first_page_text)
            
            # 2. Table Parsing - Process all pages
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Clean and normalize header row
                    header = table[0]
                    clean_header = [str(h).replace('\n', ' ').strip() if h else '' for h in header]
                    
                    # Dynamic column detection using regex patterns
                    sku_idx = _find_column_index(clean_header, [r'VENDOR\s*STYLE', r'^SKU$', r'STYLE\s*#', r'ITEM\s*#'])
                    desc_idx = _find_column_index(clean_header, [r'DESCRIPTION', r'DESC', r'ITEM\s*DESC'])
                    pack_idx = _find_column_index(clean_header, [r'PACK\s*SIZE', r'VENDOR\s*PACK', r'CASE\s*PACK', r'UNITS?\s*PER'])
                    cost_idx = _find_column_index(clean_header, [r'UNIT\s*COST', r'COST', r'PRICE'])
                    total_qty_idx = _find_column_index(clean_header, [r'TOTAL\s*QTY', r'TOTAL\s*UNITS', r'QTY\s*ORDERED'])
                    
                    # Find DC columns dynamically
                    dc_map = _find_dc_columns(clean_header)
                    
                    # Skip if SKU column not found
                    if sku_idx == -1:
                        continue
                    
                    # Determine if this is a Mother PO (no DC columns) or DC PO
                    is_mother_po = len(dc_map) == 0
                    
                    # Process data rows
                    for row in table[1:]:
                        if not row or len(row) <= sku_idx:
                            continue
                        
                        # Extract SKU
                        sku = str(row[sku_idx]).strip() if row[sku_idx] else ''
                        if not sku or sku.upper() in ['', 'TOTAL', 'SUBTOTAL']:
                            continue
                        
                        # Extract description
                        description = ''
                        if desc_idx >= 0 and len(row) > desc_idx and row[desc_idx]:
                            description = str(row[desc_idx]).strip()
                        
                        # Extract pack size
                        pack_size = 1
                        if pack_idx >= 0 and len(row) > pack_idx and row[pack_idx]:
                            try:
                                pack_size = int(str(row[pack_idx]).replace(',', '').strip())
                            except (ValueError, TypeError):
                                pack_size = 1
                        if pack_size < 1:
                            pack_size = 1
                        
                        # Extract unit cost
                        unit_cost = 0.0
                        if cost_idx >= 0 and len(row) > cost_idx and row[cost_idx]:
                            try:
                                cost_str = str(row[cost_idx]).replace('$', '').replace(',', '').strip()
                                unit_cost = float(cost_str)
                            except (ValueError, TypeError):
                                unit_cost = 0.0
                        
                        if is_mother_po:
                            # Mother PO: Use Total Qty column
                            total_qty = 0
                            if total_qty_idx >= 0 and len(row) > total_qty_idx and row[total_qty_idx]:
                                try:
                                    total_qty = int(str(row[total_qty_idx]).replace(',', '').strip())
                                except (ValueError, TypeError):
                                    total_qty = 0
                            
                            if total_qty > 0:
                                # SalesOrder# = {MMM}{PO#}
                                sales_order_num = f"{brand_prefix}{extracted_po_number}"
                                
                                parsed_items.append({
                                    'sku': sku,
                                    'description': description,
                                    'po_qty': total_qty,
                                    'pack_size': pack_size,
                                    'case_qty': math.ceil(total_qty / pack_size),
                                    'unit_cost': unit_cost,  # Keep cost for Mother PO
                                    'dc_id': '',
                                    'sales_order_num': sales_order_num,
                                    'po_number': extracted_po_number,
                                    'ship_window': extracted_ship_window,
                                    'is_mother_po': True,
                                })
                        else:
                            # DC PO: Generate 1 row per DC
                            for col_idx, dc_id in dc_map.items():
                                if col_idx >= len(row):
                                    continue
                                
                                qty_str = row[col_idx]
                                if not qty_str:
                                    continue
                                
                                try:
                                    dc_qty = int(str(qty_str).replace(',', '').strip())
                                except (ValueError, TypeError):
                                    continue
                                
                                if dc_qty <= 0:
                                    continue
                                
                                # SalesOrder# = {MMM}{Prefix}{PO#}
                                dc_prefix = dc_prefix_map.get(dc_id, dc_id[:3])
                                sales_order_num = f"{brand_prefix}{dc_prefix}{extracted_po_number}"
                                
                                parsed_items.append({
                                    'sku': sku,
                                    'description': description,
                                    'po_qty': dc_qty,
                                    'pack_size': pack_size,
                                    'case_qty': math.ceil(dc_qty / pack_size),
                                    'unit_cost': 0.0,  # Cost = 0 for DC POs
                                    'dc_id': dc_id,
                                    'sales_order_num': sales_order_num,
                                    'po_number': extracted_po_number,
                                    'ship_window': extracted_ship_window,
                                    'is_mother_po': False,
                                })
            
            if not parsed_items:
                return [], "No valid data found in PDF"
            
            return parsed_items, None
            
    except Exception as e:
        logger.error(f"Error parsing PDF: {e}")
        return [], f"Error parsing PDF: {str(e)}"


# Legacy function for backward compatibility
def parse_po_to_order_data(pdf_path: str) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    Legacy wrapper that converts new parse_po output to old format.
    Returns: (List of item dicts grouped by DC, Extracted PO Number, Extracted Ship Window)
    """
    parsed_items, error = parse_po(pdf_path)
    
    if error:
        logger.error(f"PO parsing error: {error}")
        return [], "", "Error"
    
    if not parsed_items:
        return [], "", "TBD"
    
    # Extract common metadata
    po_number = parsed_items[0].get('po_number', '') if parsed_items else ''
    ship_window = parsed_items[0].get('ship_window', 'TBD') if parsed_items else 'TBD'
    
    # Return the flat list instead of DataFrames
    return parsed_items, po_number, ship_window