from playwright.sync_api import sync_playwright

console_logs = []
ws_messages = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel="chromium")
    page = browser.new_page()

    page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: console_logs.append(f"[PAGE_ERROR] {err}"))

    def on_websocket(ws):
        print(f"WebSocket opened: {ws.url}")
        ws.on("framereceived", lambda payload: ws_messages.append(f"RECV: {payload[:500]}"))
        ws.on("close", lambda: print("WebSocket closed"))

    page.on("websocket", on_websocket)

    print("Navigating to http://localhost:3000...")
    page.goto("http://localhost:3000", timeout=15000)
    page.wait_for_load_state("networkidle")
    print("Page loaded, waiting 8 seconds for WS data...")
    page.wait_for_timeout(8000)

    page.screenshot(path="/Users/xinquanwang/AURORA/dashboard_screenshot.png", full_page=True)
    print("Screenshot saved")

    no_trades = page.locator("text=暂无交易记录").all()
    print(f"\n'暂无交易记录' elements found: {len(no_trades)}")

    trade_rows = page.locator("table tbody tr").all()
    print(f"Trade table rows found: {len(trade_rows)}")

    print(f"\n=== CONSOLE LOGS ({len(console_logs)} entries) ===")
    for log in console_logs[:80]:
        print(log)

    print(f"\n=== WS MESSAGES ({len(ws_messages)} entries) ===")
    for msg in ws_messages[:20]:
        print(msg)

    browser.close()
