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

# Buyer-specific parsing configurations
BUYER_PARSING_CONFIG = {
    'TJMAXX': {
        'sku_patterns': [r'VENDOR\s*STYLE', r'^SKU$', r'STYLE\s*#'],
        'qty_patterns': [r'TOTAL\s*QTY', r'QTY\s*ORDERED'],
        'date_format': 'MM/DD/YYYY',
    },
    'MARSHALLS': {
        'sku_patterns': [r'VENDOR\s*STYLE', r'^SKU$', r'STYLE\s*#'],
        'qty_patterns': [r'TOTAL\s*QTY', r'QTY\s*ORDERED'],
        'date_format': 'MM/DD/YYYY',
    },
    'HOMEGOODS': {
        'sku_patterns': [r'VENDOR\s*STYLE', r'^SKU$', r'STYLE\s*#'],
        'qty_patterns': [r'TOTAL\s*QTY', r'QTY\s*ORDERED'],
        'date_format': 'MM/DD/YYYY',
    },
}

def _get_brand_prefix(text: str) -> str:
    """Extract brand prefix from PO text for TJX brands."""
    text_upper = text.upper()
    for brand, prefix in TJX_BRAND_PREFIXES.items():
        if brand in text_upper:
            return prefix
    return 'MMD'  # Default prefix

def _extract_buyer(text: str, filename: str = '') -> str:
    """
    Extract Buyer name from PDF first page text.
    
    Detection logic (prioritized):
    0. Check filename for brand hints (most explicit)
    1. Look for "BUYER:" field in text (Mother PO)
    2. Check DC naming patterns (most reliable for DC POs)
    3. Look for general brand mentions in text
    4. Use DEPT# as last resort
    5. Default to 'UNKNOWN' if no match found
    
    Args:
        text: First page text from PDF
        filename: Optional filename for additional hints
        
    Returns:
        Standardized buyer name in uppercase
    """
    text_upper = text.upper()
    filename_upper = filename.upper()
    
    # Priority 0: Check filename for explicit brand hints
    if 'MARSHALL' in filename_upper:
        logger.info(f"Buyer detected from filename: MARSHALLS")
        return 'MARSHALLS'
    if 'TJMAXX' in filename_upper or 'TJ-MAXX' in filename_upper or 'TJM' in filename_upper:
        logger.info(f"Buyer detected from filename: TJMAXX")
        return 'TJMAXX'
    if 'HOMEGOODS' in filename_upper or 'HOME-GOODS' in filename_upper:
        logger.info(f"Buyer detected from filename: HOMEGOODS")
        return 'HOMEGOODS'
    
    # Priority 1: Check for BUYER: field (Mother PO specific)
    # Format: "BUYER: SHAWNTE MOORE" or "BUYER: MARIA ANDRADE"
    # The buyer name appears AFTER "BUYER:" label
    buyer_match = re.search(r'BUYER:\s*([A-Z\s]+)', text_upper)
    if buyer_match:
        buyer_name = buyer_match.group(1).strip()
        # Known buyer names to brand mapping
        if 'SHAWNTE' in buyer_name or 'MOORE' in buyer_name:
            logger.info(f"Buyer detected from BUYER field: MARSHALLS (Shawnte Moore)")
            return 'MARSHALLS'
        if 'MARIA' in buyer_name or 'ANDRADE' in buyer_name:
            logger.info(f"Buyer detected from BUYER field: HOMEGOODS (Maria Andrade)")
            return 'HOMEGOODS'
    
    # Priority 2: Check for DC naming patterns (for DC POs)
    if 'MAR PHOENIX' in text_upper or 'MAR EL PASO' in text_upper or ': MAR ' in text_upper or 'AZR: MAR' in text_upper:
        logger.info(f"Buyer detected from DC naming: MARSHALLS")
        return 'MARSHALLS'
    
    if 'TJM ' in text_upper or 'MAXX LAS VEGAS' in text_upper or 'TJM SAN ANTONIO' in text_upper:
        logger.info(f"Buyer detected from DC naming: TJMAXX")
        return 'TJMAXX'
    
    # Priority 3: Check for explicit brand mentions in general text
    if 'MARSHALLS' in text_upper:
        return 'MARSHALLS'
    
    if 'TJ MAXX' in text_upper or 'TJMAXX' in text_upper:
        return 'TJMAXX'
    
    if 'HOMEGOODS' in text_upper or 'HOME GOODS' in text_upper:
        return 'HOMEGOODS'
    
    if 'HOMESENSE' in text_upper:
        return 'HOMESENSE'
    
    if 'WINNERS' in text_upper:
        return 'WINNERS'
    
    # Priority 4: Parse by lines to find DEPT# and PO#
    lines = text.split('\n')
    dept_num = None
    po_num = None
    
    for i, line in enumerate(lines):
        line_upper = line.upper()
        
        # Format 1: Look for header line with "DEPT#" and "PO#" together (Mother PO format)
        if 'DEPT#' in line_upper and 'PO#' in line_upper:
            # Found header line, next line should have data
            if i + 1 < len(lines):
                data_line = lines[i + 1].strip()
                data_parts = data_line.split()
                
                # First element is typically DEPT#, second is PO#
                if len(data_parts) >= 2:
                    try:
                        dept_num = data_parts[0]
                        po_num = data_parts[1]
                    except:
                        pass
            break
        
        # Format 2: Look for "Dept #" header (DC PO format)
        # The data line may be a few lines down
        if 'DEPT #' in line_upper or 'DEPT# ORDER DATE' in line_upper:
            # Look in next few lines for a line starting with a number
            for j in range(i + 1, min(i + 5, len(lines))):
                candidate_line = lines[j].strip()
                candidate_parts = candidate_line.split()
                
                # Check if first element is a number (likely DEPT#)
                if candidate_parts and candidate_parts[0].isdigit():
                    dept_num = candidate_parts[0]
                    # PO# may be in a different format for DC POs
                    # Look for "PO Number: 573212" pattern earlier in text
                    po_match = re.search(r'PO NUMBER:\s*(\d+)', text_upper)
                    if po_match:
                        po_num = po_match.group(1)
                    break
            break
    
    # Use DEPT# to determine buyer (HomeGoods uses 41, others use 82)
    if dept_num:
        if dept_num == '41':
            return 'HOMEGOODS'
        elif dept_num == '82':
            # Both TJMaxx and Marshalls use DEPT# 82
            # Cannot reliably distinguish without additional context
            logger.warning(f"DEPT# 82 detected - cannot distinguish TJMaxx vs Marshalls without DC names or buyer field")
            logger.warning(f"Hint: Upload both Mother and DC PO together for accurate matching")
            return 'UNKNOWN'  # Return UNKNOWN instead of guessing
    
    logger.warning(f"Could not determine buyer from PDF text")
    return 'UNKNOWN'

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
    Extract PO prefix mapping from DC PO first page.
    DC PO format:
      Line N: "PO # 10 573212 PO # 20 573212 PO # 30 573212 ..."
      Line M: "DC #: 881 DC #: 882 DC #: 883 ..."
    
    Maps DC ID to PO prefix: {881: '10', 882: '20', 883: '30', ...}
    Returns: {dc_id: po_prefix}
    """
    prefix_map = {}
    lines = text.split('\n')
    
    po_line = None
    dc_line = None
    
    # Find the lines with PO # and DC #
    for line in lines:
        if 'PO #' in line and not po_line:
            po_line = line
        if 'DC #:' in line and not dc_line:
            dc_line = line
        if po_line and dc_line:
            break
    
    if not po_line or not dc_line:
        return prefix_map
    
    # Extract PO prefixes: "PO # 10 ...", "PO # 20 ...", etc.
    po_prefixes = re.findall(r'PO\s*#\s*(\d{2})\s+\d+', po_line)
    
    # Extract DC IDs: "DC #: 881", "DC #: 882", etc.
    dc_ids = re.findall(r'DC\s*#:\s*(\d+)', dc_line)
    
    # Map them in order
    for dc_id, prefix in zip(dc_ids, po_prefixes):
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
        'buyer': str,            # Buyer name (TJMAXX, MARSHALLS, HOMEGOODS, etc.)
        'is_mother_po': bool,    # True if Mother PO (no DC columns)
    }
    """
    parsed_items: List[Dict[str, Any]] = []
    
    logger.info(f"Starting PO parse: {pdf_path}")
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                logger.error("PDF has no pages")
                return [], "PDF has no pages"
            
            logger.info(f"PDF loaded: {len(pdf.pages)} pages")
            
            # 1. Page 1 Analysis - Extract PO Number, Ship Window, Brand
            first_page_text = pdf.pages[0].extract_text() or ""
            logger.info(f"First page text length: {len(first_page_text)} characters")
            
            # Extract PO Number - multiple patterns
            extracted_po_number = ""
            
            # Try format: "PO Number: 573212" (DC PO format)
            po_match = re.search(r'PO\s*NUMBER:\s*(\d+)', first_page_text, re.IGNORECASE)
            if po_match:
                extracted_po_number = po_match.group(1)
                logger.info(f"Found PO Number (DC format): {extracted_po_number}")
            else:
                # Mother PO format: Look for header "DOMESTIC PO#" followed by data line
                # Line N: "DEPT# DOMESTIC PO# REFERENCE# ..."
                # Line N+1: "82 835243 W173270666 ..."
                lines = first_page_text.split('\n')
                for i, line in enumerate(lines):
                    if 'DOMESTIC PO#' in line and i + 1 < len(lines):
                        # Check if this is the header line (contains multiple field names)
                        if 'DEPT#' in line and 'REFERENCE#' in line:
                            # Next line should have the actual data
                            data_line = lines[i + 1].strip()
                            # Data format: "82 835243 W173270666 ..."
                            parts = data_line.split()
                            if len(parts) >= 2 and parts[1].isdigit():
                                extracted_po_number = parts[1]
                                logger.info(f"Found PO Number (Mother PO format): {extracted_po_number}")
                                break
            
            if not extracted_po_number:
                logger.warning("PO Number not found - document may not be in expected format")
            
            # Extract Ship Window with proper date sorting
            extracted_ship_window = "TBD"
            date_pattern = r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
            dates = re.findall(date_pattern, first_page_text)
            if len(dates) >= 2:
                try:
                    from datetime import datetime
                    parsed_dates = []
                    for d in dates[:2]:
                        for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%m/%d/%y']:
                            try:
                                parsed_dates.append((datetime.strptime(d, fmt), d))
                                break
                            except:
                                continue
                    if len(parsed_dates) >= 2:
                        parsed_dates.sort(key=lambda x: x[0])
                        extracted_ship_window = f"{parsed_dates[0][1]} - {parsed_dates[1][1]}"
                    else:
                        extracted_ship_window = f"{dates[0]} - {dates[1]}"
                except:
                    extracted_ship_window = f"{dates[0]} - {dates[1]}"
            elif len(dates) == 1:
                extracted_ship_window = f"Start: {dates[0]}"
            
            # Extract Vendor - parse from data line, not header
            extracted_vendor = ""
            
            # DC PO format: Look for header "Primary Vendor" followed by data line
            # Line N: "Dept # Order Date Start Ship Date ... Primary Vendor Attention ..."
            # Line N+3: "41 7/22/2025 7/25/2025 8/8/2025 F HIGHEL INC W116487141"
            # Or: "TJX Companies... 82 7/17/2025 8/13/2025 8/20/2025 N C HIGHEL INC JULIE PARK W173270666"
            lines = first_page_text.split('\n')
            found_vendor = False
            for i, line in enumerate(lines):
                if 'Primary Vendor' in line and 'Order Date' in line:
                    # This is DC PO header, look for data line (usually 2-3 lines down)
                    for offset in range(1, 6):
                        if i + offset < len(lines):
                            data_line = lines[i + offset].strip()
                            # Match company name ending with INC, LLC, LTD, CORP, or CO
                            match = re.search(r'\d{1,2}/\d{1,2}/\d{4}\s+[A-Z]\s+[A-Z]\s+([A-Z\s]+(?:INC|LLC|LTD|CORP|CO))', data_line)
                            if not match:
                                # Try single letter version (F HIGHEL INC W...)
                                match = re.search(r'\d{1,2}/\d{1,2}/\d{4}\s+[A-Z]\s+([A-Z\s]+(?:INC|LLC|LTD|CORP|CO))', data_line)
                            if match:
                                extracted_vendor = match.group(1).strip()
                                found_vendor = True
                                break
                    if found_vendor:
                        break
            
            if not found_vendor:
                # Mother PO format: Look for header "VENDOR NAME" followed by data line
                # Line N: "DEPT# DOMESTIC PO# REFERENCE# CIR# VENDOR# VENDOR NAME FOBPOINT"
                # Line N+1: "41 573212 W116487141 E915 HIGHEL INC CITY: Laguna Hills"
                for i, line in enumerate(lines):
                    if 'VENDOR NAME' in line and 'VENDOR#' in line and i + 1 < len(lines):
                        # This is the header line, check next line for data
                        data_line = lines[i + 1]
                        # Look for company name ending with INC, LLC, etc. before "CITY:"
                        match = re.search(r'[A-Z0-9]{4}\s+([A-Z\s]+(?:INC|LLC|LTD|CORP|CO))\s+CITY:', data_line)
                        if match:
                            extracted_vendor = match.group(1).strip()
                            break
            
            # Extract Buyer (pass filename for additional hints)
            import os
            filename = os.path.basename(pdf_path)
            extracted_buyer = _extract_buyer(first_page_text, filename)
            logger.info(f"Detected Buyer: {extracted_buyer}")
            
            # Get brand prefix
            brand_prefix = _get_brand_prefix(first_page_text)
            logger.info(f"Brand Prefix: {brand_prefix}")
            
            # Get DC prefix mapping
            dc_prefix_map = _extract_po_prefix_map(first_page_text)
            
            # 2. Table Parsing - Process all pages
            total_tables_found = 0
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if tables:
                    logger.info(f"Page {page_num}: Found {len(tables)} table(s)")
                    total_tables_found += len(tables)
                
                for table_num, table in enumerate(tables, 1):
                    if not table or len(table) < 2:
                        logger.warning(f"Page {page_num} Table {table_num}: Skipped (empty or too few rows)")
                        continue
                    
                    # Clean and normalize header row
                    header = table[0]
                    clean_header = [str(h).replace('\n', ' ').strip() if h else '' for h in header]
                    logger.info(f"Page {page_num} Table {table_num} Headers: {clean_header}")
                    
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
                        logger.warning(f"Page {page_num} Table {table_num}: SKU column not found, skipping")
                        continue
                    
                    logger.info(f"Page {page_num} Table {table_num}: SKU col={sku_idx}, DC columns={len(dc_map)}, is_mother_po={len(dc_map) == 0}")
                    
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
                                    'buyer': extracted_buyer,
                                    'vendor': extracted_vendor,
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
                                dc_prefix = dc_prefix_map.get(dc_id, dc_id[-2:])
                                sales_order_num = f"{brand_prefix}{dc_prefix}{extracted_po_number}"
                                
                                parsed_items.append({
                                    'sku': sku,
                                    'description': description,
                                    'po_qty': dc_qty,
                                    'pack_size': pack_size,
                                    'case_qty': math.ceil(dc_qty / pack_size),
                                    'unit_cost': 0.0,  # Cost = 0 for DC POs
                                    'dc_id': dc_id,
                                    'dc_po_prefix': dc_prefix,  # Add PO prefix for DC PO number construction
                                    'sales_order_num': sales_order_num,
                                    'po_number': extracted_po_number,
                                    'ship_window': extracted_ship_window,
                                    'buyer': extracted_buyer,
                                    'vendor': extracted_vendor,
                                    'is_mother_po': False,
                                })
            
            if not parsed_items:
                logger.error(f"No valid data found in PDF: {pdf_path}")
                logger.error(f"Total tables found: {total_tables_found}, PO#: {extracted_po_number}, Buyer: {extracted_buyer}")
                return [], f"No valid data found in PDF. Found {total_tables_found} tables but no valid SKU rows."
            
            logger.info(f"Successfully parsed {len(parsed_items)} items from PDF")
            logger.info(f"Buyer: {extracted_buyer}, PO#: {extracted_po_number}, Vendor: {extracted_vendor}")
            return parsed_items, None
            
    except Exception as e:
        logger.error(f"Error parsing PDF {pdf_path}: {e}", exc_info=True)
        return [], f"Error parsing PDF: {str(e)}"


# Legacy function for backward compatibility
def parse_po_to_order_data(pdf_path: str) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    Legacy wrapper that converts new parse_po output to old format.
    Returns: (Flat list of parsed item dicts, Extracted PO Number, Extracted Ship Window)
    
    Note: Unlike the old implementation that returned DataFrames, this returns 
    a flat list of dicts. Each dict contains parsed PO item data with 
    dc_id, sku, description, quantities, and pricing information.
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