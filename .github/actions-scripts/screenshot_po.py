# Playwright를 사용해 프론트 페이지를 열고 data/ 내부의 첫 파일을 input[type=file]로 지정한 뒤 업로드/처리 후 스크린샷 저장합니다.
# 실제 동작을 위해서는 프론트의 input/button selector 조정을 권장합니다.
import os, sys, asyncio, time
from pathlib import Path
from playwright.async_api import async_playwright

HOST = "http://localhost:8001"
FRONT_PAGE = f"{HOST}/"      # 필요하면 "/mmd.html" 등으로 변경
DATA_DIR = Path("data")
OUT_DIR = Path("screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FILE_INPUT_SELECTORS = ["input[type='file']", "input#poFile", "input[name='file']"]
UPLOAD_BUTTON_SELECTORS = ["button[type='submit']", "button#upload", "button.upload-btn"]

async def run():
    files = [p for p in DATA_DIR.iterdir() if p.is_file()] if DATA_DIR.exists() else []
    sample_file = str(files[0]) if files else None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"], headless=True)
        page = await browser.new_page()
        await page.goto(FRONT_PAGE)
        await page.screenshot(path=OUT_DIR / "page_initial.png", full_page=True)
        if not sample_file:
            print("No sample file found in data/; captured initial page only.")
            await browser.close()
            return
        print("Using sample file:", sample_file)
        file_input = None
        for s in FILE_INPUT_SELECTORS:
            try:
                elem = await page.query_selector(s)
                if elem:
                    file_input = elem
                    print("Found file input selector:", s)
                    break
            except Exception:
                pass
        if file_input:
            await file_input.set_input_files(sample_file)
            clicked = False
            for bs in UPLOAD_BUTTON_SELECTORS:
                try:
                    btn = await page.query_selector(bs)
                    if btn:
                        print("Found upload button selector:", bs)
                        await btn.click()
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                try:
                    await file_input.evaluate("el => el.form && el.form.submit && el.form.submit()")
                    print("Tried form.submit() on file input")
                except Exception:
                    print("No upload button or form.submit available; waiting for manual processing.")
            # 처리/파싱 시간 대기 (필요하면 증가)
            await asyncio.sleep(6)
            timestamp = int(time.time())
            await page.screenshot(path=OUT_DIR / f"result_{timestamp}.png", full_page=True)
        else:
            print("No file input found; captured initial page only.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
