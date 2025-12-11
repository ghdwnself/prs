"""
PDF Parsing Test Script
Tests parsing of sample PDFs from data folder
"""
import sys
import os

# Force UTF-8 output
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from services.po_parser import parse_po
import pdfplumber
import json

def test_parse_pdf(pdf_path):
    """Parse PDF and display detailed information"""
    print(f"\n{'='*80}")
    print(f"File: {os.path.basename(pdf_path)}")
    print(f"{'='*80}\n")
    
    # 1. Extract first page text
    print("First page text extraction:")
    print("-" * 80)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if pdf.pages:
                first_page_text = pdf.pages[0].extract_text() or ""
                # Print first 30 lines
                lines = first_page_text.split('\n')[:30]
                for i, line in enumerate(lines, 1):
                    print(f"{i:2d}: {line}")
    except Exception as e:
        print(f"ERROR extracting text: {e}")
    
    print("\n")
    
    # 2. Parsing results
    print("Parsing Results:")
    print("-" * 80)
    try:
        items, error = parse_po(pdf_path)
        
        if error:
            print(f"ERROR: {error}")
            return
        
        if not items:
            print("WARNING: No items parsed")
            return
        
        # Display metadata from first item
        first = items[0]
        print(f"SUCCESS: Parsed {len(items)} items\n")
        
        print("Metadata:")
        print(f"  - PO Number: {first.get('po_number', 'N/A')}")
        print(f"  - Vendor: {first.get('vendor', 'N/A')}")
        print(f"  - Buyer: {first.get('buyer', 'N/A')}")
        print(f"  - Ship Window: {first.get('ship_window', 'N/A')}")
        print(f"  - Is Mother PO: {first.get('is_mother_po', 'N/A')}")
        
        # DC info
        dc_ids = set(item.get('dc_id', '') for item in items if item.get('dc_id'))
        if dc_ids:
            print(f"  - DC IDs: {', '.join(sorted(dc_ids))}")
        
        # Show 5 sample items
        print(f"\nSample Items (first 5):")
        for i, item in enumerate(items[:5], 1):
            print(f"\n  {i}. SKU: {item.get('sku', 'N/A')}")
            print(f"     Description: {item.get('description', 'N/A')[:50]}...")
            print(f"     PO Qty: {item.get('po_qty', 0)}")
            print(f"     Pack Size: {item.get('pack_size', 0)}")
            if item.get('dc_id'):
                print(f"     DC: {item.get('dc_id')}")
        
        # Save full results to JSON
        output_path = pdf_path.replace('.pdf', '_parsed.json').replace('.PDF', '_parsed.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        print(f"\nFull results saved: {output_path}")
        
    except Exception as e:
        print(f"ERROR during parsing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Find PDF files in data and temp folders
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
    
    # Folders to search
    search_dirs = [data_dir, temp_dir]
    
    pdf_files = []
    for search_dir in search_dirs:
        if os.path.exists(search_dir):
            for file in os.listdir(search_dir):
                if file.lower().endswith('.pdf'):
                    pdf_files.append(os.path.join(search_dir, file))
    
    if not pdf_files:
        print("ERROR: No PDF files found")
        print(f"   Please put sample PDFs in these folders:")
        print(f"   - {data_dir}")
        print(f"   - {temp_dir}")
        sys.exit(1)
    
    # Test all PDF files
    for pdf_path in pdf_files:
        test_parse_pdf(pdf_path)
