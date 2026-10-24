# P2-A.2 #observe 视觉/语义验收

**日期：** 2026-09-10  
**模式：** `http://127.0.0.1:5173/#observe`  
**证据：** `observe-acceptance-full.png` · `observe-left-01-btc.png` · `observe-acceptance-report.json`

## 七项验收

| # | 项 | 结果 | 备注 |
|---|-----|------|------|
| 1 | LEFT 01/02 来自真实 TrendSnapshot（1D/4H/1H/Relative/Funding/Eligibility/blockers） | PASS | WS CONNECTED · observatory-v1 |
| 2 | 趋势等级与 Funding 权力分离 | PASS | live: L5/5 + Funding NORMAL；EXTREME 为 strength 标签非 funding veto |
| 3 | Funding UNKNOWN 不显示为 0 | PASS | live 显示 `NORMAL · 0.0100%`；`funding_truth` 单测覆盖 null→UNKNOWN |
| 4 | REALTIME 无 synthetic | PASS | 无数据周期显示 NOT CONNECTED；3m 有真实 K 线时不补假图 |
| 5 | 3m 权力低于 HTF | PASS | Eligibility 来自 HTF mirror（WATCH）；FINAL DECISION 非 LIVE |
| 6 | 治理语义 | PASS | REALTIME FEED · READ ONLY · EXECUTION DENIED · TRADING NO-GO |
| 7 | 产品语言优先 | PASS | headline `BULL · L5/5 · EXTREME` + meta chip WATCH + blocker reason |

## 收口状态

```text
P2-A DUAL-ASSET TREND ENGINE = READ-ONLY-TRUTH-COMPLETE
ALPHA EVIDENCE: NO-EVIDENCE
OI: P2-A.4 OPTIONAL · NON-BLOCKING
```

## 修复项（验收过程中）

- `CockpitPanels.jsx`：`OperationsRow` 缺少 `realtimeMode` 导致 React 白屏
- `dashboard_feed.py`：market fetch 周期内 funding 误用 pre-ok meta → rate=null
- `observatory_snapshots.py`：FINAL DECISION disclaimer 对齐 NOT LIVE 语义
