"""
Validator Service for PO Processing System.
Provides smart inventory validation with Main-First -> Sub-Second logic.
"""
import logging
from typing import List, Dict, Any, Optional
from core.config import settings
from services.data_loader import data_loader

# 로깅 설정
logger = logging.getLogger(__name__)

# Status constants
STATUS_OK = "OK"
STATUS_INVENTORY_LOW = "⚠️ Inventory Low"
STATUS_OUT_OF_STOCK = "🚨 Out of Stock"
STATUS_PRICE_MISMATCH = "가격 불일치"
STATUS_PRODUCT_MISSING = "제품 미등록"


def resolve_safety_stock(safety_stock_value: Optional[int] = None) -> int:
    """Resolve safety stock value with sane defaults."""
    if safety_stock_value is None:
        return getattr(settings, "SAFETY_STOCK", 0)
    try:
        return max(0, int(safety_stock_value))
    except (TypeError, ValueError):
        logger.warning("Invalid safety_stock_value provided. Falling back to 0.")
        return getattr(settings, "SAFETY_STOCK", 0)


def validate_po_data(
    parsed_data_list: List[Dict[str, Any]],
    safety_stock_value: Optional[int] = None,
    stock_mode: str = "TOTAL",
    inventory_map: Optional[Dict[str, Dict]] = None,
    product_map: Optional[Dict[str, Dict]] = None
) -> List[Dict[str, Any]]:
    """
    Smart validation: price alignment + inventory check with configurable safety stock.
    
    Args:
        parsed_data_list: List of parsed PO items from po_parser
        inventory_map: Inventory data (defaults to data_loader.inventory_map)
        product_map: Product data (defaults to data_loader.product_map)
        safety_stock_value: Safety stock buffer to subtract from location stock (defaults to settings.SAFETY_STOCK or 0)
        stock_mode: Inventory source selector ("MAIN", "SUB", or "TOTAL"). Defaults to TOTAL.
        
    Returns:
        List of validated items with status and additional info
    """
    if inventory_map is None:
        inventory_map = data_loader.inventory_map
    if product_map is None:
        product_map = data_loader.product_map
    effective_safety_stock = resolve_safety_stock(safety_stock_value)

    default_stock_mode = (stock_mode or "TOTAL").strip().upper()
    if default_stock_mode not in {"MAIN", "SUB", "TOTAL"}:
        default_stock_mode = "TOTAL"
    
    validated_items: List[Dict[str, Any]] = []
    
    for item in parsed_data_list:
        sku = str(item.get('sku', '')).strip()
        po_qty = int(item.get('po_qty', 0))
        po_cost = float(item.get('unit_cost', 0.0))
        is_mother_po = item.get('is_mother_po', False)
        item_stock_mode = str(item.get('stock_mode', default_stock_mode)).strip().upper()
        if item_stock_mode not in {"MAIN", "SUB", "TOTAL"}:
            item_stock_mode = "TOTAL"
        
        # Get inventory data for SKU
        inv_data = inventory_map.get(sku, {"total": 0, "locations": {}})
        main_stock = int(inv_data.get("locations", {}).get("MAIN", 0))
        sub_stock = int(inv_data.get("locations", {}).get("SUB", 0))
        total_stock = int(inv_data.get("total", 0))
        available_main = max(0, main_stock - effective_safety_stock)
        available_sub = max(0, sub_stock - effective_safety_stock)
        available_total = max(0, total_stock - effective_safety_stock)
        available_by_mode = {
            "MAIN": available_main,
            "SUB": available_sub,
            "TOTAL": available_total
        }
        available_stock = available_by_mode.get(item_stock_mode, available_total)
        
        # Get product data for price comparison
        prod_data = product_map.get(sku, {})
        system_cost = float(prod_data.get('KeyAccountPrice_TJX', 0.0) or 0.0)

        # Safety stock is reserved by reducing available stock; required quantity stays as PO qty.
        required_qty = po_qty
        shortage = max(0, required_qty - available_stock)

        # Inventory status based on availability
        if shortage == 0:
            inventory_status = STATUS_OK
        elif available_stock > 0:
            inventory_status = STATUS_INVENTORY_LOW
        else:
            inventory_status = STATUS_OUT_OF_STOCK

        transfer_from_sub = 0
        if item_stock_mode == "MAIN" and shortage > 0 and available_sub > 0:
            transfer_from_sub = min(available_sub, shortage)
        remaining_shortage = max(0, shortage - transfer_from_sub)

        # Price check (Mother PO prioritized, but applied when both values exist)
        status_label = STATUS_OK
        price_warning = ""
        if not prod_data:
            status_label = STATUS_PRODUCT_MISSING
        elif is_mother_po or (po_cost > 0 and system_cost > 0):
            if abs(po_cost - system_cost) > 0.01:
                status_label = STATUS_PRICE_MISMATCH
                price_warning = f"PO: ${po_cost:.2f} vs System: ${system_cost:.2f}"
        elif system_cost == 0:
            status_label = STATUS_PRODUCT_MISSING

        # Final status prioritizes product/price issues over inventory, but keeps inventory flag
        status = inventory_status if status_label == STATUS_OK else status_label
        
        # Build validated item
        validated_item = {
            **item,  # Include all original fields
            'status': status,
            'status_label': status_label,
            'inventory_status': inventory_status,
            'main_stock': main_stock,
            'sub_stock': sub_stock,
            'total_stock': total_stock,
            'available_main_stock': available_main,
            'available_sub_stock': available_sub,
            'available_total_stock': available_total,
            'available_stock': available_stock,
            'required_qty': required_qty,
            'shortage': remaining_shortage,
            'transfer_from_sub': transfer_from_sub,
            'remaining_shortage': remaining_shortage,
            'system_cost': system_cost,
            'price_warning': price_warning,
            'stock_mode': item_stock_mode,
            'memo_action': item.get('memo_action', '')
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
        'out_of_stock_count': 0,
        'main_short_count': 0,
        'price_mismatch_count': 0,
        'total_units': 0,
        'total_shortage': 0,
        'total_transfer_from_sub': 0,
        'items_by_dc': {},
        'shortage_items': [],
    }
    
    for item in validated_items:
        status = item.get('status', '')
        status_label = item.get('status_label', '')
        inventory_status_val = item.get('inventory_status', status)
        po_qty = int(item.get('po_qty', 0))
        dc_id = item.get('dc_id', 'N/A')

        shortage_val = int(item.get('remaining_shortage', 0))
        available_stock = int(item.get('available_stock', 0))

        # Count by status
        if shortage_val == 0 and inventory_status_val == STATUS_OK:
            summary['ok_count'] += 1
        elif inventory_status_val == STATUS_INVENTORY_LOW or (shortage_val > 0 and available_stock > 0):
            summary['main_short_count'] += 1
        elif shortage_val > 0 or inventory_status_val == STATUS_OUT_OF_STOCK:
            summary['out_of_stock_count'] += 1
        
        # Price warnings
        if status_label == STATUS_PRICE_MISMATCH or item.get('price_warning'):
            summary['price_mismatch_count'] += 1
        
        # Totals
        summary['total_units'] += po_qty
        summary['total_shortage'] += shortage_val
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
