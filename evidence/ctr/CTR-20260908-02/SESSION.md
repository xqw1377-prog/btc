# CTR-20260908-02 — CONTROLLED LIFECYCLE COMPLETE（PASS-1）

> 证据重建说明：本会话的原始 stdout（run_output.txt）在后续治理重构中
> 从工作树丢失（目录仅存 orphan_cancel.json）。本文件由执行代理依据
> 当时会话完整输出记录重建于 P1-GOV-1，内容逐字段对齐执行时输出；
> wire 级原始 ACK 见本目录 RECONSTRUCTED_run_output.txt。
> 孤儿撤销证据 orphan_cancel.json 为原始文件（未重建）。

```text
session_id       CTR-20260908-02
contract         6b2cc7c
operator         确认按此单执行（对话正式确认单的续期窗口；
                 原单 CTR-20260908-01 因配置错误型 STOP 被机械作废，
                 同参数续期 —— 治理注记见 provenance 段）
authorization    运行时进程内范围授权（EXECUTE_AUTHORIZED 进程内翻转，
                 随进程收回；当时源码常量保持 False）
outcome          COMPLETE（P0-P5 全阶段）
exchange writes  ENTRY MARKET LONG 0.001（orderId 28576823407）
                 SL Algo STOP_MARKET SELL 0.001 @77537.0 MARK_PRICE
                 （algoId 1000000197760077）
                 CLOSE SELL/LONG 0.001（orderId 28576823441）
final position   KNOWN_FLAT（CLOSE authoritative fill 0.001）
final algo       AURORA BTCUSDT Algo 0（残腿按精确 id 撤销，CANCELLED）
V5S_*            未触碰
incident ledger  字节不变
session kill     ENGAGED（收口）
```

## 阶段记录

```text
P0  HEDGE / FLAT / 挂单0 / AURORA Algo 0 / 身份一致；mark=78320.2
P1  WIRE ACK 三方核对 OBSERVED 零问题：
    ENTRY ack status=NEW executedQty=0（fills 聚合为数量真源——
    G0-4B 合同在真实服务上成立）
    SL Algo ack orderType=STOP_MARKET / triggerPrice 77537.0 / qty 0.001
    （R1 别名修复经真实 POST 验证）
P2  entry LONG 0.001 MARKET；权威 fills 聚合 0.001
P3  ACTIVE_CONFIRMED：查询回验 NEW + workingType=MARK_PRICE + 回显一致；
    protected_qty == 0.001
P4  TRUE RESTART：新实例（ctr-restart）恢复；无重复 entry/SL；
    仓位/保护保持
P5  CLOSE SELL/LONG 0.001 → authoritative fill → KNOWN_FLAT → RECONCILED
C6  平仓后 SL 残腿 ACTIVE（孤儿）→ 按精确 id 撤销 → CANCELLED；
    qualification_close 就此补撤腿步骤（本会话的工程产出）
```

## 治理注记（P1-GOV-2 对齐）

```text
EXECUTION PROTOCOL EVIDENCE   VALID
AUTHORIZATION GOVERNANCE      NOTE：授权来自操作员正式确认单（对话），
                              但窗口文件由执行代理生成（自签机制），
                              与 CTR-03 同源的治理缺口——已在
                              P0-GOVERNANCE-REPAIR 中以硬前门封堵。
QUALIFICATION RESULT          PASS-1（本仓唯一 PASS；EXECUTE 恢复 FALSE）
```

---

## RECONSTRUCTION PROVENANCE（永久纪律，append-only）

```text
ORIGINAL RAW EVIDENCE      PARTIAL / LOST（run_output.txt 丢失，不可恢复）
EVIDENCE PACKAGE           RECONSTRUCTED-COMPLETE（依据执行时会话输出重建）
REBUILD SOURCE             执行代理的会话记录（本文件创建时唯一来源）
或然纪律                   本目录今后只允许追加 provenance/hash/引用来源；
                          任何新生成的 txt 不得称为原始执行文件。
```
