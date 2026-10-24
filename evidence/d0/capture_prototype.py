from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(__file__).resolve().parent
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.goto("http://127.0.0.1:4173/#disconnected", wait_until="networkidle")
    page.screenshot(path=str(out / "01-disconnected.png"), full_page=True)

    page.get_by_role("tab", name="STALE").click()
    page.wait_for_timeout(250)
    page.screenshot(path=str(out / "02-stale.png"), full_page=True)

    page.get_by_role("tab", name="UNKNOWN").click()
    page.wait_for_timeout(250)
    page.screenshot(path=str(out / "03-unknown.png"), full_page=True)

    page.get_by_role("tab", name="交易所 OK").click()
    page.wait_for_timeout(250)
    page.screenshot(path=str(out / "04-exchange-ok-collapsed.png"), full_page=True)

    page.get_by_role("button", name="1m 诊断").click()
    page.wait_for_timeout(350)
    page.screenshot(path=str(out / "05-diagnostic-open.png"), full_page=True)

    page.get_by_role("tab", name="L1 OPEN 夹具").click()
    page.wait_for_timeout(250)
    page.screenshot(path=str(out / "06-overlay-fixture.png"), full_page=True)
    browser.close()
print("captured")
