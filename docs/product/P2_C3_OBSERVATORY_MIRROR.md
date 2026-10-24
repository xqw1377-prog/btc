# P2-C.3 Observatory Event Mirror

Status: `PASS`  
Date: `2026-09-10`

```text
P2-C.0 CONTRACT HARNESS       CONTRACT-PASS
P2-C.1 EVENT TRUTH            READ-ONLY-TRUTH-COMPLETE
P2-C.2 ACTION ELIGIBILITY     CONTRACT-PASS · READ-ONLY
P2-C.3 OBSERVATORY MIRROR     PASS

P2-C EVENT DECISION PIPELINE  READ-ONLY-SEMANTICS-COMPLETE

OFFICIAL SOURCE INGESTION     NOT CONNECTED / NOT IMPLEMENTED
EVENT ACTIVE                  UNREACHABLE
EVENT EXECUTION               NOT IMPLEMENTED
ALPHA EVIDENCE                NO-EVIDENCE
```

## 纪律（冻结）

```text
aurora/event_observatory.py              = backend projection (C1 + C2 → bundle)
aurora-dashboard/src/cockpit/eventMirror.js = display mapping only (no recompute)
tests/test_event_observatory_c3.py       = ACCEPTANCE AUTHORITY
```

**后端给结论，LEFT 给答案，RIGHT 给证据。** 前端不得从 impact + trend + priced_in 重算 ELIGIBLE。

## 数据流

```text
event_truth + event_action_eligibility
        ↓
build_event_observatory_snapshot()
        ↓
observatory.event
        ↓
eventMirror.js → LEFT 04 + RIGHT EVENT EVIDENCE
```

## Source 状态（fail-closed）

| 状态 | UI |
|------|-----|
| `SOURCE_NOT_CONNECTED` | OFFICIAL EVENT SOURCES NOT CONNECTED · Event State UNKNOWN |
| `NO_EVENT_OBSERVED` | SOURCE HEALTH OK · NO EVENT OBSERVED（仅 connected 时） |
| `SOURCE_ERROR` | SOURCE ERROR · EVENT TRUTH UNKNOWN |

## C3 验收门

| # | 语义 | 状态 |
|---|------|------|
| 1 | LEFT 04 eligibility 全由后端 EventSnapshot 给出 | PASS |
| 2 | E3 ≠ ELIGIBLE 可展示 | PASS |
| 3 | ELIGIBLE ≠ ACTIVE 常驻 | PASS |
| 4 | RISK_OFF 无 SHORT/SELL | PASS |
| 5 | priced_in UNKNOWN → NO BOOST | PASS |
| 6 | NOT_CONNECTED ≠ NO EVENT | PASS |
| 7 | SOURCE_ERROR 不退化为空 events | PASS |
| 8 | RETRACTED 显示 revoked/revision | PASS |
| 9 | first_observed_at / version / cluster 可追溯 | PASS |
| 10 | REALTIME 顶栏 READ ONLY · EXECUTION DENIED | PASS |

## 明确不做

- 真实官方源抓取（独立后续能力）
- P3 Brain / target risk / execution
- 宣称「实时事件引擎完整上线」
