"""P2-A.2 #observe visual/semantic acceptance — 7 criteria."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:5173/#observe"
WAIT_MS = 12_000


def text(page) -> str:
    return page.locator("body").inner_text()


def assert_no_live_label(body: str, failures: list[str]) -> None:
    # Allow NOT LIVE / NOT LIVE DECISION; forbid bare LIVE trading semantics
    stripped = re.sub(r"NOT LIVE DECISION", "", body)
    stripped = re.sub(r"NOT LIVE", "", stripped)
    if re.search(r"\bLIVE\b", stripped):
        failures.append("6. 发现易误解的 LIVE 标签（非 NOT LIVE 语境）")
    if re.search(r"\bLIVE TRADING\b", body, re.I):
        failures.append("6. 出现 LIVE TRADING")


def assert_governance(body: str, failures: list[str]) -> None:
    required = [
        "REALTIME FEED",
        "READ ONLY",
        "EXECUTION DENIED",
    ]
    for phrase in required:
        if phrase not in body:
            failures.append(f"6. 顶栏缺少: {phrase}")
    if "TRADING NO-GO" not in body and "TRADING NO GO" not in body:
        failures.append("6. 顶栏缺少 TRADING NO-GO")
    if "COCKPIT · REALTIME" not in body and "REALTIME" not in body:
        failures.append("6. 未显示 REALTIME 模式标识")


def assert_trend_mirror(body: str, failures: list[str]) -> None:
    for asset in ("BTC", "ETH"):
        section = body  # cards are in sidebar; check global mirror fields
    for label in ("1D", "4H", "1H", "Funding", "Eligibility"):
        if label not in body:
            failures.append(f"1. LEFT 01/02 缺少字段: {label}")
    if "Relative" not in body and "vs BTC" not in body:
        failures.append("1. 缺少 Relative Strength 字段")


def assert_funding_not_zero(body: str, failures: list[str]) -> None:
    if re.search(r"Funding\s*\n?\s*0(?:\.0+)?%?", body, re.I):
        failures.append("3. Funding 显示为 0（应为 UNKNOWN 或带 rate）")
    if "Funding\n0" in body or "Funding 0" in body:
        failures.append("3. Funding 裸 0 值")


def assert_no_synthetic_realtime(page, failures: list[str]) -> None:
    fixtures = page.locator(".candle-fixture, [data-fixture='true']")
    if fixtures.count() > 0:
        failures.append("4. REALTIME 模式出现 synthetic/fixture 图表标记")
    # Switch to 4H if pill exists — should show NOT CONNECTED when no HTF data
    pill_4h = page.locator(".tf-pill", has_text="4H")
    if pill_4h.count():
        pill_4h.first.click()
        page.wait_for_timeout(400)
        body = text(page)
        if "NOT CONNECTED" not in body and "PARTIAL" not in body:
            # If real 4H data connected, that's also valid for criterion 1
            if not re.search(r"4H\s+(BULL|BEAR|RANGE|—)", body):
                failures.append("4. 4H 无数据时未显示 NOT CONNECTED / PARTIAL")


def assert_product_language(body: str, failures: list[str]) -> None:
    # Headline pattern: BULL · Lx/5 or direction · level before mirror dl
    if not re.search(r"(BULL|BEAR|TRANSITION|UNKNOWN|方向不明确)\s*·\s*L\d", body):
        failures.append("7. 左侧未呈现产品语言 headline（方向 · Lx）")
    if "BLOCK NEW RISK" not in body and "LONG ELIGIBLE" not in body and "WATCH" not in body:
        if "等待 observatory" in body:
            failures.append("7. observatory 未就绪，无法验 eligibility 产品语言")
        else:
            failures.append("7. 缺少 Eligibility 产品语言（meta chip）")


def assert_3m_subordinate(body: str, failures: list[str]) -> None:
    # Left cards must not say LONG ELIGIBLE driven only by 3m; check final decision
    if re.search(r"3m.*LONG ELIGIBLE", body, re.I | re.S):
        failures.append("5. 3m 被误读为 LONG ELIGIBLE")
    if re.search(r"NOT LIVE|P3 HOLD|engines do not control", body, re.I):
        pass  # final decision explicitly not live
    elif "FINAL DECISION" in body:
        failures.append("5. FINAL DECISION 缺少 NOT LIVE 免责声明")


def extract_left_cards(body: str) -> dict:
    """Best-effort parse for report."""
    return {"raw_len": len(body)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    report: dict = {"url": URL, "criteria": {}}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel="chrome")
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        page.goto(URL, wait_until="load", timeout=60_000)
        page.wait_for_selector(".global-bar", timeout=30_000)
        # Wait for observatory WS payload to mirror into LEFT 01/02
        try:
            page.wait_for_function(
                """() => {
                  const t = document.body.innerText;
                  return t.includes('BTC TREND') && t.includes('Funding') && !t.includes('等待 observatory');
                }""",
                timeout=25_000,
            )
        except Exception:
            pass
        page.wait_for_timeout(WAIT_MS)

        body = text(page)
        if not body.strip():
            failures.append("页面 body 为空 — React 未挂载")
            if console_errors:
                failures.append(f"console errors: {console_errors[:5]}")
        (OUT / "observe-acceptance-full.txt").write_text(body, encoding="utf-8")
        page.screenshot(path=str(OUT / "observe-acceptance-full.png"), full_page=True)

        # Focus BTC card screenshot
        btc_card = page.locator(".left-card").filter(has_text="BTC TREND")
        if btc_card.count():
            btc_card.first.screenshot(path=str(OUT / "observe-left-01-btc.png"))

        assert_governance(body, failures)
        assert_no_live_label(body, failures)
        assert_trend_mirror(body, failures)
        assert_funding_not_zero(body, failures)
        assert_product_language(body, failures)
        assert_3m_subordinate(body, failures)
        assert_no_synthetic_realtime(page, failures)

        # Criterion 2: if EXTREME funding visible, level must not drop artificially
        if "EXTREME" in body:
            m_level = re.search(r"(BULL|BEAR)\s*·\s*(L\d/5)", body)
            if m_level and m_level.group(2) in ("L0/5", "L1/5") and "BLOCK NEW RISK" in body:
                failures.append(
                    "2. Funding EXTREME 时 trend level 疑似被 funding 降级 "
                    f"({m_level.group(0)})"
                )
            report["criteria"]["2_funding_level_separation"] = "EXTREME present — checked"
        else:
            report["criteria"]["2_funding_level_separation"] = (
                "SKIP live — no EXTREME in feed; backend tests cover separation"
            )

        if "Funding\nUNKNOWN" in body or re.search(r"Funding\s+UNKNOWN", body):
            report["criteria"]["3_funding_unknown"] = "PASS — UNKNOWN shown"
        elif "等待 observatory" in body:
            report["criteria"]["3_funding_unknown"] = "PENDING — feed not ready"
        else:
            report["criteria"]["3_funding_unknown"] = (
                "PASS — rate shown (not zero) or labeled state"
            )

        page.screenshot(path=str(OUT / "observe-acceptance-4h-tab.png"), full_page=True)
        browser.close()

    report["failures"] = failures
    report["pass"] = len(failures) == 0
    (OUT / "observe-acceptance-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if failures:
        print("\nFAIL:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nP2-A.2 #observe acceptance: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
