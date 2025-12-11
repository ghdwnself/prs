# Changelog

## [2.0.2] - 2025-12-10
### Fixed
- **CSV 로딩 에러 수정**: inventory_template.csv의 잘못된 데이터('error' 문자열) 처리 개선
  - `_safe_int()` 헬퍼 함수 추가로 안전한 정수 변환
  - 잘못된 행은 경고 로그와 함께 건너뛰도록 수정
- **파일 업로드 이슈 해결**: index.html의 `.upload-zone` 클래스명을 `.po-upload-zone`으로 변경하여 app.js와의 이벤트 충돌 해결

### Changed
- **매직 넘버 상수화**: 팔렛 제약 값들을 system_config.json에서 로드하도록 변경
  - `palletizer.py`, `palletizer_emd.py` 생성자에 config 파라미터 추가
  - 최대 높이(68"), 최대 무게(2500lb), 팔렛 무게(40lb)를 설정 파일로 관리
- **에러 핸들링 강화**: Firebase 조회, CSV 로딩, PDF 파싱 등 주요 지점에 try-except 블록 보강
- **로깅 개선**: 더 상세한 디버깅 정보 추가
  - SKU별 조회 결과 로그 (Firebase/Cache)
  - PDF 파싱 단계별 로그
  - 재고 로딩 상세 정보 (성공/실패 SKU 수)

## [2.0.1] - 2025-12-10
### Added/Changed/Fixed
- Mother/DC 검증 응답을 총 수량 기준으로 단순화하고 PO 메타, 재고 모드(통합/MAIN/SUB), 팔렛 요약을 포함하도록 반환
- 프론트엔드 검증 화면을 수량 중심 요약, PO 정보 카드, 재고 보기 토글, DC 팔렛 블록, 간결한 토스트/스피너로 개편
- CSV 내보내기와 요약 배너를 새 데이터 구조(수량·카톤, 재고 모드) 기준으로 정비

## [2.0.0] - 2025-12-09

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

### Removed
- Firebase 프론트엔드 인증 설정(`firebase_config.js`)과 로그인 UI 요소를 제거하여 무인증 흐름으로 단순화
- 레거시 `mmd.html` 업로드 페이지 및 네비게이션 경로를 정리하고 `index.html` PO Validation 진입점으로 통합

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
