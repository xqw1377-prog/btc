# P2-C.1 Event Truth Foundation

Status: `READ-ONLY-TRUTH-COMPLETE`  
Date: `2026-09-10`

```text
P2-C.0 CONTRACT HARNESS    CONTRACT-PASS
P2-C.1 EVENT TRUTH         READ-ONLY-TRUTH-COMPLETE

EVENT IMPACT               NOT IMPLEMENTED
PRICED-IN                  NOT IMPLEMENTED
BOOST ELIGIBILITY          NOT IMPLEMENTED

P2-C.2                     HOLD
P2-C.3                     HOLD
P3                         HOLD
EXECUTION                  DENIED
```

## 纪律（冻结）

```text
tests/fixtures/event_truth_c1_cases.py  = CONTRACT FIXTURE
tests/test_event_truth_c1.py              = ACCEPTANCE AUTHORITY
aurora/event_truth.py                     = READ-ONLY TRUTH ONLY
```

**硬边界：** AURORA 在 `first_observed_at` 之前，不得拥有该事实。

## 四时间字段

| 字段 | 语义 |
|------|------|
| `event_time` | 事件实际发生 / 统计期对应时间 |
| `source_published_at` | 官方源声称发布时间 |
| `first_observed_at` | AURORA 第一次真正看到它 |
| `last_observed_at` | 最近一次确认该版本 |

## Revision Chain（append-only）

| 字段 | 语义 |
|------|------|
| `event_key` | 稳定身份（如 `US_CPI_2026_08`） |
| `event_version` | 单调递增版本 |
| `supersedes_version` | 上一版本号 |
| `payload_hash` | 内容指纹（幂等去重） |
| `revision_type` | INITIAL / REVISION / RETRACTION |
| `retracted` | 撤回标记 |

查询：`truth_as_of(as_of_ms)` 只返回 `first_observed_at <= as_of` 的最新版本。

## Source Registry v1

首批四类官方源：`FED` · `BLS` · `BEA` · `SEC`  
每 entry 含：`source_id` · `authority_type` · `domain` · `event_classes[]` · `parser_version` · `timezone` · `freshness_policy` · `enabled`

## Source Health（fail-closed）

抓取失败 ≠ 今天没有事件：

| 状态 | 含义 |
|------|------|
| `NO_EVENT_OBSERVED` | 源连通、窗口内无新事件 |
| `SOURCE_NOT_CONNECTED` | 源未启用 / 未接入 |
| `SOURCE_STALE` | 超过 freshness_policy |
| `SOURCE_ERROR` | 抓取失败 |
| `UNKNOWN` | 无法判定 |

## Consensus 收紧

无独立、带时间戳的 consensus truth source 时：

```text
expected_value = null
surprise       = null
consensus_truth_state = UNKNOWN
```

## C1-1 ~ C1-10 回归门

| ID | 语义 | 状态 |
|----|------|------|
| **C1-1** | 官方首发 → event_key + v1 | PASS |
| **C1-2** | 相同 payload 重复抓取 → IDEMPOTENT | PASS |
| **C1-3** | 真实修订 → append v2，v1 保留 | PASS |
| **C1-4** | RETRACTION → append，不 delete | PASS |
| **C1-5** | as_of 在 revision 前 → 仅旧版本 | PASS |
| **C1-6** | 回溯修订注入 → LOOKAHEAD_REJECTED | PASS |
| **C1-7** | 同源转载 20 次 → corroboration 不增 | PASS |
| **C1-8** | 两权威源冲突 → CONFLICT | PASS |
| **C1-9** | fetch failure → SOURCE_ERROR | PASS |
| **C1-10** | 无 consensus 源 → expected/surprise null | PASS |

## 明确不做（本刀）

- Impact Score / Priced-in / Event Boost / RISK_OFF
- P3 Brain / 前端 Event Mirror / 任何交易行为
- LLM 直接赋 EVENT_TRUTH（仅 EXTRACTED_CANDIDATE → 结构化对齐后升级）
