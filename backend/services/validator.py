"""
Validator Service for PO Processing System.
Provides smart inventory validation with Main-First -> Sub-Second logic.
"""
import logging
from typing import List, Dict, Any, Optional
from services.data_loader import data_loader

# 로깅 설정
logger = logging.getLogger(__name__)

# Status constants
STATUS_OK = "OK"
STATUS_MAIN_SHORT = "⚠️ Main Short. Transfer from Sub"
STATUS_OUT_OF_STOCK = "🚨 Out of Stock"
STATUS_PRICE_MISMATCH = "💰 Price Mismatch"


def validate_po_data(
    parsed_data_list: List[Dict[str, Any]],
    inventory_map: Optional[Dict[str, Dict]] = None,
    product_map: Optional[Dict[str, Dict]] = None,
    safety_stock: int = 50
) -> List[Dict[str, Any]]:
    """
    Smart inventory validation: Check MAIN first, then SUB.
    
    Args:
        parsed_data_list: List of parsed PO items from po_parser
        inventory_map: Inventory data (defaults to data_loader.inventory_map)
        product_map: Product data (defaults to data_loader.product_map)
        safety_stock: Safety stock buffer to add to requirements
        
    Returns:
        List of validated items with status and additional info
    """
    if inventory_map is None:
        inventory_map = data_loader.inventory_map
    if product_map is None:
        product_map = data_loader.product_map
    
    validated_items: List[Dict[str, Any]] = []
    
    for item in parsed_data_list:
        sku = str(item.get('sku', '')).strip()
        po_qty = int(item.get('po_qty', 0))
        po_cost = float(item.get('unit_cost', 0.0))
        is_mother_po = item.get('is_mother_po', False)
        
        # Get inventory data for SKU
        inv_data = inventory_map.get(sku, {"total": 0, "locations": {}})
        main_stock = int(inv_data.get("locations", {}).get("MAIN", 0))
        sub_stock = int(inv_data.get("locations", {}).get("SUB", 0))
        total_stock = int(inv_data.get("total", 0))
        
        # Get product data for price comparison
        prod_data = product_map.get(sku, {})
        system_cost = float(prod_data.get('KeyAccountPrice_TJX', 0.0) or 0.0)
        
        # Calculate required quantity (PO qty + safety stock)
        required_qty = po_qty + safety_stock
        
        # Status logic: Check MAIN first, then SUB
        status = STATUS_OK
        shortage = 0
        transfer_from_sub = 0
        remaining_shortage = 0
        
        if main_stock >= required_qty:
            # MAIN has enough stock
            status = STATUS_OK
        else:
            # MAIN is short
            shortage = required_qty - main_stock
            
            if sub_stock >= shortage:
                # SUB can cover the shortage
                status = STATUS_MAIN_SHORT
                transfer_from_sub = shortage
            else:
                # Neither MAIN nor SUB has enough
                status = STATUS_OUT_OF_STOCK
                transfer_from_sub = sub_stock  # Transfer what's available
                remaining_shortage = shortage - sub_stock
        
        # Price check for Mother POs
        price_warning = ""
        if is_mother_po and po_cost > 0 and system_cost > 0:
            # Allow small difference (e.g., rounding)
            if abs(po_cost - system_cost) > 0.01:
                price_warning = f"PO: ${po_cost:.2f} vs System: ${system_cost:.2f}"
        
        # Build validated item
        validated_item = {
            **item,  # Include all original fields
            'status': status,
            'main_stock': main_stock,
            'sub_stock': sub_stock,
            'total_stock': total_stock,
            'required_qty': required_qty,
            'shortage': shortage,
            'transfer_from_sub': transfer_from_sub,
            'remaining_shortage': remaining_shortage,
            'system_cost': system_cost,
            'price_warning': price_warning,
        }
        
        validated_items.append(validated_item)
    
    return validated_items


def get_validation_summary(validated_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a summary of validation results.
    
    Args:
        validated_items: List of validated items from validate_po_data
        
    Returns:
        Summary dict with counts and totals
    """
    summary = {
        'total_items': len(validated_items),
        'ok_count': 0,
        'main_short_count': 0,
        'out_of_stock_count': 0,
        'price_mismatch_count': 0,
        'total_units': 0,
        'total_shortage': 0,
        'total_transfer_from_sub': 0,
        'items_by_dc': {},
        'shortage_items': [],
    }
    
    for item in validated_items:
        status = item.get('status', '')
        po_qty = int(item.get('po_qty', 0))
        dc_id = item.get('dc_id', 'N/A')
        
        # Count by status
        if status == STATUS_OK:
            summary['ok_count'] += 1
        elif status == STATUS_MAIN_SHORT:
            summary['main_short_count'] += 1
        elif status == STATUS_OUT_OF_STOCK:
            summary['out_of_stock_count'] += 1
        
        # Price warnings
        if item.get('price_warning'):
            summary['price_mismatch_count'] += 1
        
        # Totals
        summary['total_units'] += po_qty
        summary['total_shortage'] += item.get('remaining_shortage', 0)
        summary['total_transfer_from_sub'] += item.get('transfer_from_sub', 0)
        
        # Group by DC
        if dc_id not in summary['items_by_dc']:
            summary['items_by_dc'][dc_id] = {
                'count': 0,
                'units': 0,
                'shortage': 0,
            }
        summary['items_by_dc'][dc_id]['count'] += 1
        summary['items_by_dc'][dc_id]['units'] += po_qty
        summary['items_by_dc'][dc_id]['shortage'] += item.get('remaining_shortage', 0)
        
        # Track shortage items
        if item.get('remaining_shortage', 0) > 0:
            summary['shortage_items'].append({
                'sku': item.get('sku'),
                'dc_id': dc_id,
                'shortage': item.get('remaining_shortage'),
            })
    
    return summary
