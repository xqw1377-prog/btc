# CONTROLLED TESTNET REQUALIFICATION — DESIGN REVIEW（仅审查，未授权执行）

> 审查日：2026-09-08  
> 对象：三个 PREBUILT / UNAUTHORIZED 文件  
> 依据合同：G0-4B/C 执行事实与保护生命周期、G0-5 身份与配置隔离、
> G0-4D/R1 Algo schema 事实、DISPOSITION、以及用户冻结的写入边界清单  
> 结论：**候选草案可作基础；存在 1 个身份门漏洞、5 个阶段缺失，
> 修复前不得授权执行。**

## 逐文件裁定

### 1. `docs/product/CONTROLLED_TESTNET_REQUAL.md` — 采纳为基底（需修订）

做对的：kill 处理方向与裁定一致（事故 kill 只读保留 + 会话账本自管
kill，收口后 engage）；两套事实禁止混写；范围/规模/永久禁止清单完整；
"一次受控试验 PASS ≠ 恢复系统交易"表述正确。

必须修订的：
- **前置状态过时**：引用 `G0-4D b0b1ef1 CLOSED-READONLY`，早于
  R1（95ece99）与读协议更正；须更新为
  `G0-4D EXECUTION COMPLETE / EVIDENCE SEALED / READ PROTOCOL PASS
  (R1) / QUALIFICATION GATE UNBLOCKED`。
- **缺 SUBMIT ACK 现场验证阶段**（见审查项 A）。
- 冻结条件多为文字，未逐条映射到代码中的强制检查点（见审查项 C/E）。

### 2. `aurora/ops_controlled_requal.py` — 有条件采纳（修复后才可授权）

做对的（与冻结合同一致）：
- ConfigSource、显式 env 路径、TESTNET 门、指纹必须等于事故账户
  `3fbc5d4f1f9ddc7d`，否则 ACCOUNT_IDENTITY_DRIFT（G0-5C ✓）
- 会话账本 `state/testnet/<fp>/controlled_requal.db` 物理隔离；
  `ensure_ledger_migrated` 被源码扫描禁止带入（比生产路径更严格，
  正确——会话不应继承事故状态）
- 事故 kill 只读快照 + 意外 CLEAR 即拒；会话收口（含成功）必
  engage 会话 kill；事故账本前后摘要比对 ✓
- MAX_QTY=0.001 / MAX_NOTIONAL=120 / 单腿 LONG / 单 intent /
  禁止复用事故 client id ✓
- 默认 PLAN-only；执行旗标存在也仍 DENIED ✓
- 保护链路走内核 G0-4B 语义（fills 权威 sizing、PROTECTED 状态、
  recover() 无未决、protected_qty==qty）✓

缺口（授权前必须修复）：
- **A.（裁定级）SUBMIT ACK 现场验证阶段缺失。** R1 只证明了 GET 侧
  orderType 别名；POST Algo 的 ACK schema 未经过真实服务。run_session
  直接信任 open_position 的返回，没有"首次真实 ACK 的原始 wire 响应
  落证据 + 与提交意图/规范化 AlgoOrderFact 三方核对"的阶段。
- **B. workingType==MARK_PRICE 未被强制验证。** 合同写了，代码没有：
  SL 腿确认必须包含对 query fact 的 workingType 检查（V5S_* 的
  CONTRACT_PRICE 正是区分所有权与合同的现场信号；R1 后 query 已可解析）。
- **C. "ACTIVE_CONFIRMED" 隐式而非显式。** PROTECTED 依赖后续
  recover() 的查询同步，但没有一条显式的"按 clientAlgoId 查询回验
  SL 状态=NEW/ACTIVE + triggerPrice/qty 回显"的确认步骤。
- **D. 会话前只读基线阶段缺失。** 文档要求"先只读：FLAT、无 BTC
  普通挂单、无 AURORA BTC Algo"，run_session 没有实现（应复用
  G0-4D probe 读取路径作为 Phase 0，任一不满足即拒开）。
- **E. 名义上限可被绕过。** plan()/assert_scale 的 notional 检查依赖
  调用方传入 mark_price；省略时只查 qty 上限。可执行版本必须以
  只读观察到的权威标记价（GET）计算 notional，并同时校验交易所
  MIN_NOTIONAL 过滤器。
- **F. 身份门可被跳过。** 直接调用 `plan()`（source=None）时身份与
  模式检查整段被跳过。可执行版本必须无条件执行身份检查。

### 3. `tests/test_controlled_requal.py` — 随代码修订一并扩展

现有：计划门禁、上限、事故 id 禁用、路径隔离、无 production_main/
migrated 源码扫描、离线单会话（含事故账本字节不变）✓。
缺：Phase 0 基线、WIRE ACK 验证、workingType 确认、mark_price 权威
来源、身份门无条件性——随上述修复补齐。

## 处置建议（与裁定一致）

```text
STATUS     PREBUILT / UNAUTHORIZED → CANDIDATE DRAFT（评审通过后转正式）
EXECUTE    DENIED
COMMIT     DENIED（三文件保持未提交；本审查与合同文档同样暂不提交）
DELETE     NO
MODIFY     HOLD（修复按本审查 + 合同文档实施，实施包单独授权提交）
```

审查通过的证据化顺序：修复 → 全树测试 → 独立提交 → 用户单独发出
第一次受控写入开工令。
