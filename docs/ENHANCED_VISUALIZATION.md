# Enhanced PO Review Visualization

## Overview

This document describes the enhanced visual indicators and inventory display features added to the Mother PO Review workflow.

## Features

### 1. Price Match Visualization

The system now provides clear visual feedback on price accuracy when comparing PO prices against system prices from Firebase.

#### Visual Indicators

- **✓ Price Match** (Green)
  - Displayed when PO price matches system price (within $0.01 tolerance)
  - CSS class: `price-match`
  - Color: Green (#10b981)

- **✗ Price Mismatch** (Red)
  - Displayed when PO price differs from system price
  - CSS class: `price-mismatch`
  - Color: Red (#ef4444)
  - Shows comparison: "PO: $X.XX vs System: $Y.YY"

#### Implementation

```css
.price-match {
    color: #10b981;
    font-weight: 600;
}

.price-match::before {
    content: '✓ ';
    font-weight: 700;
}
```

### 2. Inventory Status Highlighting

Enhanced stock level visualization with three-tier status system.

#### Status Levels

1. **✓ Adequate Stock** (Green)
   - Sufficient inventory to fulfill order + safety stock
   - Status: "OK"
   - CSS class: `stock-adequate`
   - Background: Light green (#d1fae5)
   - Text: Dark green (#065f46)

2. **⚠ Low Stock** (Yellow)
   - Stock available but requires transfer from SUB to MAIN
   - Status: "Main Short. Transfer from Sub"
   - CSS class: `stock-low`
   - Background: Light yellow (#fef3c7)
   - Text: Dark yellow/brown (#92400e)

3. **🚨 Out of Stock** (Red)
   - Insufficient inventory even after SUB transfer
   - Status: "Out of Stock"
   - CSS class: `stock-out`
   - Background: Light red (#fee2e2)
   - Text: Dark red (#991b1b)

#### CSS Implementation

```css
.stock-adequate {
    background-color: #d1fae5;
    color: #065f46;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: 600;
}

.stock-adequate::before {
    content: '✓ ';
}
```

### 3. MAIN/SUB/TOTAL Inventory Display

Enhanced inventory breakdown showing stock levels by location.

#### Display Format

```
Main:  500
Sub:   200
─────────
Total: 700
```

#### Location Types

- **MAIN**: Primary warehouse location (blue highlight)
- **SUB**: Secondary/overflow warehouse location (purple highlight)
- **TOTAL**: Combined total across all locations

#### CSS Implementation

```css
.inventory-display {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 0.85rem;
}

.inventory-main {
    color: #2563eb; /* Blue for MAIN */
}

.inventory-sub {
    color: #7c3aed; /* Purple for SUB */
}

.inventory-total {
    color: #0f172a;
    border-top: 1px solid #e2e8f0;
    padding-top: 2px;
    margin-top: 2px;
}
```

## Data Flow

### Backend (validator.py)

1. **Price Validation**
   ```python
   if is_mother_po and po_cost > 0 and system_cost > 0:
       if abs(po_cost - system_cost) > 0.01:
           price_warning = f"PO: ${po_cost:.2f} vs System: ${system_cost:.2f}"
   ```

2. **Inventory Validation**
   ```python
   if main_stock >= required_qty:
       status = STATUS_OK
   else:
       shortage = required_qty - main_stock
       if sub_stock >= shortage:
           status = STATUS_MAIN_SHORT
           transfer_from_sub = shortage
       else:
           status = STATUS_OUT_OF_STOCK
           remaining_shortage = shortage - sub_stock
   ```

### Frontend (mmd.html)

1. **Extract Data**
   ```javascript
   const mainInv = item['Main Stock'] || item['main_stock'] || 0;
   const subInv = item['Sub Stock'] || item['sub_stock'] || 0;
   const totalInv = item['Total Stock'] || (mainInv + subInv);
   ```

2. **Determine Status Class**
   ```javascript
   let stockStatusClass = 'stock-adequate';
   if (shortage > 0 || totalInv < poQty) {
       stockStatusClass = 'stock-out';
   } else if (normalizedStatus === 'warning') {
       stockStatusClass = 'stock-low';
   }
   ```

3. **Build Inventory HTML**
   ```javascript
   const inventoryHtml = `
       <div class="inventory-display">
           <div class="inventory-row">
               <span class="inventory-label">Main:</span>
               <span class="inventory-value inventory-main">${mainInv}</span>
           </div>
           <div class="inventory-row">
               <span class="inventory-label">Sub:</span>
               <span class="inventory-value inventory-sub">${subInv}</span>
           </div>
           <div class="inventory-row inventory-total">
               <span class="inventory-label">Total:</span>
               <span class="inventory-value">${totalInv}</span>
           </div>
       </div>
   `;
   ```

## Table Layout

The enhanced MMD detail table now includes:

| Column | Description |
|--------|-------------|
| Status | Combined status + stock indicator |
| SKU | Product SKU |
| Desc | Product description (truncated) |
| PO Qty | Quantity from PO |
| Inventory | MAIN/SUB/TOTAL breakdown |
| Price | Unit price from PO |
| Price Status | Match/Mismatch indicator |
| Message | Warnings or issues |

## Color Scheme

### Status Colors
- **OK/Match**: Green (#10b981)
- **Warning/Low**: Yellow/Amber (#f59e0b, #92400e)
- **Critical/Out**: Red (#ef4444, #991b1b)

### Location Colors
- **MAIN**: Blue (#2563eb)
- **SUB**: Purple (#7c3aed)
- **TOTAL**: Black (#0f172a)

## Browser Compatibility

All CSS features use standard properties compatible with:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Accessibility

- Color is not the only indicator (icons and text are also used)
- Sufficient color contrast ratios (WCAG AA compliant)
- Semantic HTML for screen readers
- Clear labels for all data points

## Testing

To test the enhanced visualization:

1. Upload a Mother PO PDF via MMD workflow
2. Click on any DC card to expand details
3. Observe:
   - Price status column shows Match/Mismatch
   - Inventory column shows MAIN/SUB/TOTAL breakdown
   - Status badges are color-coded (green/yellow/red)
   - Row backgrounds highlight critical items

## Future Enhancements

- [ ] Add inventory level graphs/charts
- [ ] Historical price comparison
- [ ] Predictive stock alerts
- [ ] Customizable color schemes
- [ ] Export detailed reports with visual indicators
