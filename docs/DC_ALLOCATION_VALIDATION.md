# DC Allocation Validation Feature

## Overview

The DC Allocation Validation feature verifies that Distribution Center (DC) Purchase Orders correctly allocate quantities from a Mother PO. This ensures that the sum of all DC allocations matches the Mother PO requirements at the SKU level.

## Use Cases

1. **Mother PO Split Validation**: When a Mother PO is split across multiple DCs, validate that the total allocated quantity matches the original order
2. **Over/Under Allocation Detection**: Identify SKUs that are over-allocated or under-allocated to DCs
3. **Extra SKU Detection**: Find SKUs in DC POs that don't exist in the Mother PO

## How It Works

### Backend API

**Endpoint**: `POST /api/validate_dc_allocation`

**Request Payload**:
```json
{
  "mother_po_items": [
    {
      "sku": "12345",
      "po_qty": 1000,
      "dc_id": "N/A"
    }
  ],
  "dc_po_items": [
    {
      "sku": "12345",
      "po_qty": 500,
      "dc_id": "0789"
    },
    {
      "sku": "12345",
      "po_qty": 500,
      "dc_id": "0456"
    }
  ]
}
```

**Response**:
```json
{
  "status": "success",
  "validation": {
    "is_valid": true,
    "total_skus_mother": 1,
    "total_skus_dc": 1,
    "mismatches": [],
    "summary": {
      "matching_skus": 1,
      "mismatched_skus": 0
    }
  }
}
```

### Validation Logic

1. **Aggregate Mother PO**: Sum all quantities by SKU from Mother PO
2. **Aggregate DC POs**: Sum all quantities by SKU across all DC POs
3. **Compare**: For each SKU, compare Mother PO total vs DC total
4. **Classify Mismatches**:
   - `over`: DC total > Mother PO total
   - `under`: DC total < Mother PO total  
   - `extra`: SKU in DC PO but not in Mother PO

### Frontend UI

The DC Validation page (`dc_validation.html`) provides:

1. **Dual Upload Interface**: Upload both Mother PO and DC PO PDFs
2. **Automatic Analysis**: Each PDF is parsed using the existing `/api/analyze_po` endpoint
3. **Validation Results**:
   - Success banner if all allocations match
   - Detailed mismatch table showing:
     - SKU
     - Mother PO quantity
     - DC total quantity
     - Difference
     - Status (over/under/extra)
     - DC breakdown (which DCs have which quantities)

## Visual Indicators

- **✅ Success**: Green banner when all allocations match
- **⚠️ Warning**: Yellow highlighting for minor issues
- **🚨 Error**: Red banner and highlighting for critical mismatches
- **Status Badges**:
  - `Over-allocated`: Yellow background
  - `Under-allocated`: Red background
  - `Extra SKU`: Pink background

## Example Scenarios

### Scenario 1: Perfect Match
- Mother PO: SKU 12345 = 1000 units
- DC#0789: 500 units
- DC#0456: 500 units
- **Result**: ✅ Valid (500 + 500 = 1000)

### Scenario 2: Under-Allocated
- Mother PO: SKU 12345 = 1000 units
- DC#0789: 400 units
- DC#0456: 500 units
- **Result**: ⚠️ Under by 100 units (400 + 500 = 900)

### Scenario 3: Over-Allocated
- Mother PO: SKU 12345 = 1000 units
- DC#0789: 600 units
- DC#0456: 500 units
- **Result**: ⚠️ Over by 100 units (600 + 500 = 1100)

### Scenario 4: Extra SKU
- Mother PO: SKU 12345 = 1000 units
- DC#0789: SKU 12345 = 1000 units
- DC#0789: SKU 67890 = 500 units (not in Mother PO)
- **Result**: ⚠️ Extra SKU 67890

## Integration

This feature integrates with the existing PO processing workflow:

1. Uses the same PO parser (`parse_po_to_order_data`) for both Mother and DC POs
2. Returns data in the same format as the MMD workflow
3. Can be accessed from the main navigation sidebar
4. Does not interfere with existing MMD/EMD workflows

## Future Enhancements

- [ ] Batch validation of multiple DC POs at once
- [ ] Export validation report to Excel
- [ ] Store validation history in database
- [ ] Email notifications for validation failures
- [ ] Integration with approval workflow
