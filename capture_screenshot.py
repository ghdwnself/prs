import os
from playwright.sync_api import sync_playwright

def capture_screenshot(url, output_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_timeout(6000)  # Data load waiting time (increased for complex PO processing)
        page.screenshot(path=output_path)
        browser.close()

if __name__ == "__main__":
    # Ensure screenshots directory exists
    os.makedirs("screenshots", exist_ok=True)
    capture_screenshot("http://localhost:8001", "screenshots/screenshot.png")
