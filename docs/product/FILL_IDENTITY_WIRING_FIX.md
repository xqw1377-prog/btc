# S2 入口接线修正清单（W1–W4 · 仅评审，未实现）

> 状态：**WIRING-CORRECTION-PLAN / 待评审**。四项阻断的事实认定
> 全部接受；本清单是窄范围修正方案与真实证明场景，不默认迁移
> 真实账本、不削弱任何旧断言、T-D2/T-D3 留在 S2 范围内。

## 0. 接口依赖报告（先行——W1 根因）

`aurora.kernel.port.Fill` 现有字段：`fill_id, client_order_id,
qty(float), price(float), fee(float), side, filled_at`——**缺
symbol、qty_raw/price_raw/fee_raw、fee_asset、origin**。这是
事实依赖缺口，不是已实现能力。当前接线用"包装成 HISTORY + str
(float) 补造 raw"绕过了它——撤回该做法。

**依赖决策（二选一，请裁定）**：

- **D-a（推荐）**：扩展 `Fill` 为可选字段载体——`symbol: Optional
  [str]`、`qty_raw/price_raw/fee_raw: Optional[str]`、`fee_asset:
  Optional[str]`。旧调用方不填=显式 UNKNOWN（走未解析路径，不再
  假装历史）；新调用方（venue 事件入口）必填 raw。字段添加是
  冻结合同 §1.2 的 EVENT 义务在数据结构上的体现，非 S1 schema
  变更。
- **D-b**：新建 `VenueFillEvent` 数据类（不改 `Fill`），入口层
  以它为输入；`Fill` 保留给旧测试/内核构造。

无论哪种：**不存在"从 float 补造 raw"的路径**——没有 raw 就是
UNKNOWN，不进入 EVENT 比较。

## 1. 新事件输入模型（W1 修正）

```text
apply_fill_event(venue_fill) 的新事件路径（固有 EVENT）：
  必须：symbol、qty_raw、price_raw（有限严格正——非法 → 入口
        ValueError，先于任何 DB 写入）
  可选：fee_raw（缺=UNKNOWN；提供则须合法）、fee_asset（与
        fee_raw 联动：KNOWM 费用必须有资产）
  禁止：读载荷 origin（模式=EVENT 由调用路径固定）

旧 Fill（无 raw/symbol）→ 不再包装成 HISTORY：
  symbol 缺失 → ATTRIBUTION 不可判定 → IDENTITY_UNRESOLVED
  （隔离告警，不熔断减仓）——与 T-I5 一致
  即：旧形态事件在迁移后世界天然是"信息不足的迟到事件"，
  正确语义是未解析，不是降级比较。
```

**旧账本兼容策略**：`insert_fill`（REAL 通道）仍服务于内核自建
行（合成调整/对账事实行）——这些是**账本自身写入**（可信路径），
以 HISTORY 模式比较重放；**venue 迟到事件**（apply_fill_event）
一律 EVENT 模式。两个调用路径在调用处声明，互不降级。

## 2. INCOMPLETE ≠ DUPLICATE（W2 修正）

撤回"INCOMPLETE → 幂等 DUPLICATE"。恢复三裁决入口语义：

```text
MISMATCH    → IDENTITY_CONFLICT（kill + 仓位 UNKNOWN）
INCOMPLETE  → IDENTITY_UNRESOLVED（隔离告警 + 不收养 + 不写行；
              不判冲突、不判确认重复；不熔断减仓）
MATCH       → DUPLICATE（幂等）
```

不熔断一切：IDENTITY_UNRESOLVED 记 kill 告警位（可审计）但
`block_reduce=False`（与 cross_tier_compare 同界）。

## 3. 仅唯一约束冲突才进重复比较（W3 修正）

```text
except sqlite3.IntegrityError as exc:
    if not _is_target_unique_violation(exc, fill_id):
        raise                      # NOT NULL/CHECK/FK/其他全上抛
    existing = get(fill_id)
    if existing is None:
        raise                      # 无法定位重复行=异常路径，上抛
    ... 统一校验器 ...
```

`_is_target_unique_violation`：错误消息含 UNIQUE 且能以 fill_id
定位到既有行；二者缺一即上抛。评审复现（side=None 触发 NOT NULL）
将正确上抛而非 return False。

## 4. 九项测试的真实证明场景（W4 修正——全部重写断言）

| ID | 真实证明（新断言） |
|---|---|
| T-I4e | venue 事件缺 symbol → `IDENTITY_UNRESOLVED`（ATTRIBUTION 不可判定），不是 DUPLICATE |
| T-I5 | 旧形态 Fill（无 raw）重放既有行 → `IDENTITY_UNRESOLVED`：不写新行 + kill 告警位 + `block_reduce` 语义；真正 MATCH（raw 齐备且相等）才 DUPLICATE |
| T-DB1 | FK（引用不存在订单）与 NOT NULL（side=None）**均**上抛，无一返回 False |
| T-DB2 | 真实 CHECK 违约（qty=0 直接 INSERT）vs FillIdentityConflict（同 ID 不同内容）——异常类型可区分 |
| T-C1 | 并发一致重放：恰一行 **且 errs 为空**（无静默异常） |
| T-C2 | 并发冲突：至少一个 FillIdentityConflict 可见；无静默丢失 |
| T-X1 | 两入口对同一字段变异矩阵（qty/price/side/cid 四维）逐项产生**同冲突字段集**——不再只查异常文本 |
| T-X2 | 既有 W43 断言（EventEntryConflictBypassTests）不改一字全绿 |
| T-D3 | 入口层接线显式重算：同一 fill 的 realized_pnl 重算事件**追加行**，历史行值不变（前后快照对比） |
| T-D2（补回 S2） | DEVIATION 发生时：损益标 UNRELIABLE、阻断新增风险、**不设仓位 UNKNOWN、不阻减仓**（close 通道仍可用） |

## 5. 范围与不动项

- S1 schema/接口：**零修改**（Fill 扩展待 D-a/D-b 裁定后实施，
  若裁 D-a 则作为本修正包的接口依赖变更单独说明提交）；
- 真实账本不迁移；旧断言不削弱；核心校验器已验部分不动；
- T-D2/T-D3 属 S2（本清单第 4 节已纳入）。

## 6. 交付顺序（批准后）

固定基线 → 红测试（W1–W4 复现 + 上表断言）→ 依赖实现（D-a 或
D-b）→ 入口修正 → 全新克隆专项+全套 → 固定 SHA + 映射 + 日志。
