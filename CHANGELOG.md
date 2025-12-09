# Changelog

## [Unreleased] - 2025-12-09

### Added

#### Mother PO Review Enhancements
- **Price Match Visualization**: Added visual indicators for price accuracy
  - Green checkmark (✓) for price matches
  - Red X (✗) for price mismatches with comparison values
  - Displays "PO: $X.XX vs System: $Y.YY" for mismatches

- **Enhanced Stock Status Highlighting**: Three-tier color-coded system
  - Green (✓): Adequate stock available
  - Yellow (⚠): Low stock, requires transfer from SUB warehouse
  - Red (🚨): Out of stock, insufficient inventory

- **MAIN/SUB/TOTAL Inventory Display**: Detailed inventory breakdown
  - MAIN warehouse stock (blue highlight)
  - SUB warehouse stock (purple highlight)  
  - TOTAL combined stock with visual separator
  - Clear labels and color coding for each location

#### DC PO Allocation Validation
- **New Backend Endpoint**: `/api/validate_dc_allocation`
  - Validates DC PO allocations against Mother PO requirements
  - Verifies sum of DC allocations equals Mother PO SKU-level totals
  - Error handling for non-numeric values
  - Returns detailed mismatch information

- **DC Validation Page**: New `dc_validation.html` interface
  - Dual-upload interface for Mother PO and DC PO files
  - Real-time validation with detailed results
  - Mismatch table showing:
    - SKU, Mother PO qty, DC total qty, difference
    - Status classification (over/under/extra)
    - DC breakdown by distribution center
  - Color-coded status badges

#### Admin Dashboard Enhancements
- **Re-Reviewed PO Dashboard**: New section for tracking processed POs
  - Display PO number, buyer name, review date
  - Show total SKUs and total units
  - Status tracking (Approved/Pending Review)
  - View details button for each PO

- **Backend Endpoint**: `/api/admin/reviewed_pos`
  - Scans history directory for processed POs
  - Extracts summary statistics from history files
  - Returns sorted list of reviewed POs

#### Documentation
- `docs/DC_ALLOCATION_VALIDATION.md`: Complete guide for DC validation feature
  - API documentation with examples
  - Validation logic explanation
  - Use case scenarios
  - Integration details

- `docs/ENHANCED_VISUALIZATION.md`: Visual indicator documentation
  - Color scheme reference
  - CSS implementation details
  - Data flow diagrams
  - Testing instructions
  - Accessibility notes

### Changed

#### Frontend
- **MMD Detail Table**: Enhanced with new columns
  - Added "Inventory" column with MAIN/SUB/TOTAL breakdown
  - Added "Price Status" column for match/mismatch indicators
  - Improved status display with clearer visual indicators
  - Fixed CSS class conflicts

#### Backend
- **Error Handling**: Improved numeric conversion in DC allocation validation
  - Try-except blocks for all int/float conversions
  - Logging for invalid data warnings
  - Defaults to 0 for non-numeric values

#### CI/CD
- Removed GitHub Actions workflows and related scripts (deferred for future use)

#### CSS
- **New Style Classes**: Added comprehensive visual indicator styles
  - `.price-match`, `.price-mismatch` for price validation
  - `.stock-adequate`, `.stock-low`, `.stock-out` for inventory status
  - `.inventory-display`, `.inventory-main`, `.inventory-sub`, `.inventory-total`
  - Status badge styles for DC validation page

### Fixed
- CSS class conflict in MMD detail table (separated status classes)
- Empty span element in table rows (removed placeholder)
- Missing error handling for numeric conversions in DC validation

### Security
- ✅ CodeQL security scan passed with 0 alerts
- ✅ No new vulnerabilities introduced
- ✅ Input validation added for numeric fields
- ✅ Error handling prevents crash on invalid data

### Testing
- Server starts successfully without errors
- All pages load correctly with new features
- Admin dashboard displays re-reviewed PO section
- MMD workflow page shows enhanced visualization
- DC validation page is accessible and functional

### Compatibility
- ✅ Backward compatible with existing workflows
- ✅ No breaking changes to existing APIs
- ✅ Frontend handles both old and new field names
- ✅ Works with existing PO parser and validator

### Performance
- No significant performance impact
- New endpoints have minimal overhead
- File scanning in admin uses existing patterns
- CSS additions are lightweight

---

## Notes

This release focuses on enhancing the user experience for PO review workflows with better visual feedback and adding DC allocation validation capabilities. All changes maintain backward compatibility with existing code.

### Migration Guide
No migration required. All new features are additions that work alongside existing functionality.

### Known Issues
None at this time.

### Future Enhancements
- Batch validation of multiple DC POs
- Export validation reports to Excel
- Historical price comparison charts
- Inventory level graphs
- Customizable color schemes
- Email notifications for validation failures
