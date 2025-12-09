# Role: Python Backend Developer (FastAPI/Logistics/Firebase)

# Objective
Implement the full Mother PO + Child PO integration workflow, including multi-location inventory validation against a configured safety stock (default 0), and total quantity/price alignment checks.

# Context: Safety Stock Change
The system MUST default safety_stock to 0. The value will be retrieved from settings (e.g., settings.SAFETY_STOCK) and managed via the Admin settings endpoint.

## Task 1: Refactor `routers/mmd.py` (Controller)
**Goal:** Create a new endpoint to handle simultaneous upload of Mother and Child POs, and orchestrate validation.
- **Endpoint:** Create a new POST endpoint, `/api/mmd/upload_integrated`. It must accept two file parts (Mother PO and Child PO).
- **Flow:**
  1. Parse both files using `po_parser.parse_po_integrated`.
  2. Perform total quantity/amount alignment check between Mother and Child PO aggregates.
  3. Call `validator.validate_po_data` on the resulting item list.
  4. Return the fully validated item list and alignment check summary to the frontend.

## Task 2: Update `services/po_parser.py`
**Goal:** Handle dual input, match POs, and verify quantity alignment.
- **Method:** `parse_po_integrated(mother_po_path, child_po_path)`
- **Logic:**
  1. Parse both files for Headers (PO#, Dates, Amounts).
  2. **Match:** Use Child PO Header's Mother PO reference to confirm linkage.
  3. **Output:** Merge results into a single list of dicts.
  4. **Crucial Alignment Check:** Return the difference between `Mother PO Total Units/Amount` vs. `Sum of Child PO Units/Amount`. (This is needed for the frontend's alignment badge).
- **Data Structure:** Output should be a List[Dict] compatible with `validator.py`.

## Task 3: Update `services/data_loader.py`
**Goal:** Load inventory with location and ensure compatibility with config.
- **Method:** `load_csv_to_memory`
- **Logic:** Must store inventory as nested dict (MAIN/SUB split).
  ```python
    self.inventory_map = {
        "SKU_ID": {
            "total": 150,
            "locations": { "MAIN": 100, "SUB": 50 }
        }
    }
