"""P2-B.3 #observe ETH/BTC mirror acceptance — 8 criteria."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:5173/#observe"
WAIT_MS = 14_000


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel="chrome")
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.goto(URL, wait_until="load", timeout=60_000)
        page.wait_for_selector(".global-bar", timeout=30_000)
        try:
            page.wait_for_function(
                """() => document.body.innerText.includes('ETH/BTC')""",
                timeout=25_000,
            )
        except Exception:
            pass
        page.wait_for_timeout(WAIT_MS)
        body = page.locator("body").inner_text()
        (OUT / "observe-p2b3-full.txt").write_text(body, encoding="utf-8")
        page.screenshot(path=str(OUT / "observe-p2b3-full.png"), full_page=True)

        card = page.locator(".left-card").filter(
            has=page.locator(".left-card-index", has_text="03")
        )
        if card.count():
            card.first.click(force=True)
            try:
                page.wait_for_selector(".eth-btc-panel.is-highlight", timeout=2500)
            except Exception:
                failures.append("8. 点击 LEFT 03 未高亮 RIGHT ETH/BTC 区")
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / "observe-p2b3-left03-focus.png"), full_page=True)

        browser.close()

    if "买入 ETH" in body or "BUY ETH" in body:
        failures.append("2. 出现「买入 ETH」类措辞")
    if re.search(r"target_weight|target portfolio", body, re.I):
        failures.append("3. 出现 target_weight / target portfolio")
    if "SYNTHETIC_USDT_RATIO" not in body and "SYNTHETIC" not in body:
        failures.append("6. 缺少 SYNTHETIC_USDT_RATIO 来源声明")
    if "NOT EXECUTABLE" not in body.upper() and "NOT EXECUTABLE ETHBTC" not in body.upper():
        failures.append("6. 缺少 NOT EXECUTABLE ETHBTC PRICE")
    if re.search(r"ex_post_cycle|cycle_high_final|cycle.progress|distance_to_final", body, re.I):
        failures.append("7. 出现未来高点衍生字段")
    for gov in ("REALTIME FEED", "READ ONLY", "EXECUTION DENIED", "TRADING NO-GO"):
        if gov not in body:
            failures.append(f"8. 顶栏缺少 {gov}")
    if "ETH CANDIDATE" in body or "ETH_CANDIDATE" in body:
        if "CHEAP" in body and "ELIGIBLE" in body and "INCREASE ETH ELIGIBLE" not in body:
            pass  # B1 style OK
    if "VALUE TRUTH UNKNOWN" in body or "NO REALLOCATION" in body:
        if "BTC RETURN" in body and "VALUE TRUTH UNKNOWN" in body:
            failures.append("4. UNKNOWN 场景出现 BTC RETURN")

    report = {"url": URL, "failures": failures, "pass": len(failures) == 0}
    (OUT / "observe-p2b3-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if failures:
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("P2-B.3 #observe acceptance: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
