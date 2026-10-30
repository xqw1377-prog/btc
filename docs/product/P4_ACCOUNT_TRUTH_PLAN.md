# P4 权威账户真相 — 纯文档方案

Status: `CHANGES-REQUIRED / IMPLEMENTATION NOT AUTHORIZED`  
Date: `2026-10-30`  
修订: `P4-P1～P7 已写入本候选，待复审。本修订不是开工令，也不把方案改判为通过。`

```text
本文件 = 会计恒等式、证据对象、阻断清单
本文件 ≠ 开工令
本文件 ≠ 账户权威已经建立
本文件 ≠ 执行资格

P4 ACCOUNT TRUTH PLAN    = CHANGES-REQUIRED
P4 IMPLEMENTATION        = NOT AUTHORIZED
P3-R3.1                  = CLOSED / RUNTIME-PASS / READ-ONLY
EXECUTION ELIGIBILITY    = DENIED
LIVE                     = NO-GO
REAL TESTNET WRITE       = DENIED
TRADING AUTHORITY        = UNCHANGED
EXECUTE_AUTHORIZED       = FALSE
KILL / INCIDENT_LOCK     = 不解除

E2 / E1                  = FROZEN
S1 / S2 / S3             = CLOSED / OFFLINE PASS
费用投影消费方 / funding = 未授权
真实账户 / 接线 / 迁移   = 未授权
P3-R3.2 OBSERVATORY      = HOLD
P3-R4 EXECUTION          = FORBIDDEN / HOLD
事故副本演练             = 仍未独立验证
```

开发授权格式（未签发）：

```text
「批准 P4 权威账户真相只读开工」
```

在这句出现之前，不新增账户真相模块，不把快照接进 `adjudicate_runtime`，不读真实账户，不打开交易所连接，不迁移 `state/kernel_ledger.db`。

R3.1 关闭只说明只读裁决链成立。它不提供账户权威，也不提供下单资格。

---

## 0. 纯函数与它不碰的状态

计算是纯函数。绑定历史由调用方注入。函数只返回拟追加的绑定，不打开数据库，不写文件，不改输入。

```text
evaluate_account_truth(
    scope,
    balances,
    liabilities,
    positions,
    fee_manifest,
    funding_manifest,
    quotes,
    venue_reported_equity,
    ledger_reconstruction,
    binding_state,
    collection_proofs,
    policy,
    evaluation_at,
) -> {
    snapshot,
    binding_proposal,
}
```

`binding_state` 缺席时，提案为 `REFUSED`，阻断码 `BINDING_STATE_ABSENT`。函数不把缺席当成空历史，也不就地执行第一次绑定。

持久化若将来另签，只能是一份与内核账本隔离的追加层，并且只追加本函数已经返回的提案。本阶段不建这层，也不接真实账本。

---

## 1. 明确不回答

- 不证明保护已经 `ACTIVE_CONFIRMED`。
- 不证明可以下单。`execution_eligibility` 保持 `DENIED`，`order_intent` 保持 `ABSENT`。
- 不把账户未知折叠成整张决策卡未知。
- 不计算是否跑赢 BTC HODL，不产出 Excess BTC。
- 不把 E0 的 quote 权益当成 BTC NAV。E0 的 `funding_paid` 默认值不是已知资金费为零。
- 不把 S3 离线投影当成交易所已经确认的费用。
- 不修改 E2/E1，不重开 S1/S2/S3。
- 夹具跑通只证明计算和校验。它不建立现实账户权威。

---

## 2. 快照形状

签名里的负债、交易所报告权益、完整性清单和血缘，必须出现在快照上。

```text
calculation_ok           true | false
account_authority        ESTABLISHED | NOT_ESTABLISHED
new_risk_usable          false | true
reality_authority        NOT_ESTABLISHED          # 本阶段恒为这个值
btc_nav                  十进制文本 | null
btc_nav_unit             BTC | null
btc_nav_trace            下列分项，未知则为 null
    spot_equity_btc
    futures_wallet_btc
    unrealized_pnl_btc
    liability_btc
arithmetic_policy_version
balances                 已验证清单 | null
liabilities              已验证清单 | null
positions                FLAT | KNOWN | UNKNOWN | MALFORMED
fee_manifest             见 §6，含血缘
funding_manifest         见 §6，含血缘
set_completeness         见 §3，含血缘
venue_reported_equity    见 §8，含血缘
ledger_reconstruction    见 §8，含血缘
reconciliation           MATCH | MISMATCH | UNAVAILABLE | NOT_INDEPENDENT
binding_proposal         APPEND | REPLAY | CONFLICT | REFUSED
blockers
source_claim             SYNTHETIC | UNVERIFIED | AUTHORITATIVE
as_of
evaluation_at
scope_version
canonical_version        aurora-canonical-json-v1
hash_alg                 sha256
```

`null`、空串、缺失键都是未知。显式十进制 `0` 才是已知的零。负的净权益若其余校验都通过，保持负数，不改成 `0`。

本阶段任何输入的 `reality_authority` 都是 `NOT_ESTABLISHED`。`source_claim` 为 `SYNTHETIC` 或 `UNVERIFIED` 时，`account_authority` 为 `NOT_ESTABLISHED`，`new_risk_usable` 为 false。自报 `AUTHORITATIVE` 而没有通过 §4 的采集证明时，同样不得升级。

规范化沿用 `aurora-canonical-json-v1` 与 `sha256`。`arithmetic_policy_version` 进入快照内容身份。

---

## 3. 范围、集合与余额

五个轴分开，不允许塞进一个 `market_mode`：

```text
environment       MAINNET | TESTNET | FIXTURE
account_ref       不透明引用，不是密钥
sub_account_ref   显式引用，或 PRIMARY
product           SPOT | USDS_M
position_mode     ONE_WAY | HEDGE | NOT_APPLICABLE
margin_mode       CROSS | ISOLATED | NOT_APPLICABLE
```

`SPOT` 的 `position_mode` 与 `margin_mode` 必须是 `NOT_APPLICABLE`。`USDS_M` 必须写明 `ONE_WAY` 或 `HEDGE`，以及 `CROSS` 或 `ISOLATED`。其他产品、币本位、期权、交割合约：`UNSUPPORTED_PRODUCT`，不发布净值。

第一版合约只接受现货，以及 USDⓈ-M 线性永续。

集合完整性是一份显式证明，不是“调用方说已知”：

```text
required_assets
observed_assets
required_positions
observed_positions
proof_kind          EXPLICIT_SET_EQUAL
```

四个集合两两对应相等才算完整。证明缺失：`SET_INCOMPLETE`。同一钱包同一资产重复，或同一持仓身份重复：`DUPLICATE_ROW`。这两种情况都不发布净值。

持仓身份是 `environment + account_ref + sub_account_ref + product + symbol + side`。

余额行：

```text
product
wallet              SPOT 或 USDS_M 的钱包名
asset
free                十进制 | 缺席
locked              十进制 | 缺席
total               十进制 | 缺席
status              KNOWN
```

`free`、`locked`、`total` 互斥使用：

- 三者都在：`total` 必须精确等于 `free + locked`，净值只用 `total`。
- 只有 `free` 和 `locked`：合计作为 `total`，净值只用这一次。
- 只有 `total`：净值用 `total`。
- 只有 `free` 或只有 `locked`：`BALANCE_INCOMPLETE`。
- 把 `free` 和 `total` 同时加进净值：`DOUBLE_COUNT`。

余额或负债为负：`SIGN_MISMATCH`。负债是单独的非负欠款行。内部划转行不是资产。纳入范围内的划转净额必须精确为 `0`，否则 `TRANSFER_SCOPE_UNBALANCED`。划转不能因为只看见入账一侧而增加净资产。

`account_ref` 缺失、为空，或像密钥材料：`ACCOUNT_IDENTITY_UNFIXED`。

---

## 4. 来源声明与采集证明

来源声明和可信采集是两件事。

```text
source_claim
collection_proof | null
    receipt_ref
    account_binding     environment + account_ref + sub_account_ref
    raw_response_hash   原始响应规范正文的 sha256
    verifier            具名责任，不是布尔值
    verified_at
```

证明要同时满足：绑定与快照范围一致，原始响应哈希存在，验证责任存在。否则 `COLLECTION_PROOF_INVALID`。

本阶段夹具的 `source_claim` 只能是 `SYNTHETIC`。即便每个字段都写成 `AUTHORITATIVE` 并附上一份看起来完整的证明，`reality_authority` 与 `account_authority` 仍是 `NOT_ESTABLISHED`，`new_risk_usable` 仍是 false。夹具证明的是公式和校验，不是这个账户在现实中的权威。

---

## 5. 持仓与线性合约盈亏

现货数量在余额里。USDⓈ-M 永续在持仓里。持仓贡献的是权益，不是名义本金。

持仓行必填：

```text
symbol
contract_kind         LINEAR_PERPETUAL
side                  LONG | SHORT
qty                   基础资产数量，十进制，≥ 0
contract_multiplier   十进制
entry_price           结算资产价格，十进制，> 0
mark_price            结算资产价格，十进制，> 0
settlement_asset
```

`contract_multiplier` 缺席，或不是精确的 `1`：`UNSUPPORTED_CONTRACT`。方向由 `side` 决定，多头为 `+1`，空头为 `-1`。

```text
unrealized_pnl_settle =
    direction * qty * contract_multiplier * (mark_price - entry_price)

futures_equity_settle =
    wallet_balance_settle + unrealized_pnl_settle
```

`wallet_balance_settle` 是该结算资产在 USDⓈ-M 钱包中的余额，不含名义本金。`includes_settled_flows` 必须为 true：已结算手续费、funding 和已实现盈亏已经在钱包余额里。缺席或为 false：`WALLET_FLOW_BASIS_UNKNOWN`。事件账只用于核对和重建，不再加进或扣出净值。

冻结例子：期货钱包 `1000 USDT`，`0.1 BTC` 多头，开仓价与标记价都是 `100000 USDT`。未实现盈亏为 `0`，期货权益为 `1000 USDT`。净值路径里不出现额外的 `0.1 BTC`。

空头在标记价高于开仓价时，未实现盈亏为负；标记价低于开仓价时为正。负的未实现盈亏是盈亏项，不是非法负余额。`futures_equity_settle` 可以为负，然后按 §7 换成 BTC；结果为负时保持负数。

`HEDGE` 下两条腿分别计算。同一合约两侧都非零时不得合并成一条净额；腿的归属缺失为 `POSITION_MODE_UNKNOWN`。

持仓结构：

- `FLAT`：证明过的空列表，或每条数量都是显式 `0` 且 `status=KNOWN`。
- `KNOWN`：上面的必填字段齐全且通过算术规则。
- 缺键、`null`、空串、`UNKNOWN`：`UNKNOWN`。
- 垃圾结构：`MALFORMED`。畸形不是空仓。

本模块不发出 `ACTIVE_CONFIRMED`。

---

## 6. 费用与 funding 的窗口

事件身份是：

```text
environment + account_ref + sub_account_ref + event_type + stable_id
```

裸 `tranId` 不是身份。同一用户、同一 `incomeType` 下的 `tranId` 才有交易所侧的唯一性；跨事件类型的相同标识不得合并。同一身份、正文不同：`EVENT_IDENTITY_CONFLICT`，不覆盖旧绑定。

窗口：

```text
window_from          含起点，带时区
window_to            不含终点，带时区
query_filter         必须等于声明的环境、账户、事件类型和符号范围
pages_fetched
pages_declared
page_end_token       COMPLETE 时必须为 null
truncated            COMPLETE 时必须为 false
retained_from        交易所历史保留起点 | null
zero_event_proof     见下
lineage              receipt_ref + raw_response_hash
```

| 观察 | 判定 |
|---|---|
| 整包缺失 | `UNKNOWN` |
| 分页失败、`truncated=true`、页声明不一致、`page_end_token` 仍在 | `INCOMPLETE` |
| `retained_from` 晚于 `window_from` | `INCOMPLETE`（历史被截断） |
| 事件列表为空，且 `zero_event_proof` 覆盖同一过滤器和同一分页终点 | `COMPLETE`，合计为已知 `0` |
| 事件列表为空，但没有零事件证明 | `UNKNOWN`，合计不是 `0` |
| 身份齐全、正文一致、分页结束、保留范围覆盖窗口 | `COMPLETE` |
| 迟到事件 | 新的窗口版本；旧绑定正文不变 |

`UNKNOWN` 与 `INCOMPLETE` 都使 `btc_nav` 为 `null`。S3 关闭和 funding 模块存在，都不把窗口标成 `COMPLETE`。

---

## 7. BTC NAV

单位是 BTC。报价来自本次输入的 `quote_version`，函数内部不另取价。

```text
spot_equity_settle 按各资产换成 BTC 后相加
futures_equity_btc = futures_equity_settle / 该结算资产的 BTC 报价
liability_btc      按同一组报价换成 BTC

btc_nav = spot_equity_btc + futures_equity_btc - liability_btc
```

`futures_equity_btc` 用的是钱包余额加未实现盈亏，不是 `qty * mark_price`。名义本金出现在净值分项里：`NOTIONAL_REJECTED`。

非 BTC 数量换成 BTC 时，使用该资产钉住的正向有限报价。已知非零数量缺少报价：`QUOTE_UNPINNED`。已知为零的数量不需要报价。数量未知时，报价存在也不足以发布净值。

报价必须严格大于 `0` 且有限。`0` 或负数：`QUOTE_INVALID`。非有限：`NON_FINITE`，标记保留，不先变成 `null` 再发布。

下列情况整份 `btc_nav` 为 `null`，不发布部分和：组件未知、过期、畸形、集合不完整、重复行、划转不平、费用或 funding 窗口未完成、对账不可用或不独立、精度不足。

已结算费用、funding、已实现盈亏只留在钱包余额里。事件合计进入账本重建和对账，不进入上面的加法。

---

## 8. 三面与血缘

三面必须是同一 `environment`、同一 `account_ref`、同一 `sub_account_ref`、同一产品集合、同一计价 `as_of`。范围或时点不一致：`SCOPE_MISMATCH`。

| 面 | 输入 | 血缘 |
|---|---|---|
| 计价面 | §7 由余额、未实现盈亏、负债和钉住报价算出 | 这些组件的内容哈希 |
| 交易所权益面 | `venue_reported_equity`：金额、资产、`as_of`、范围 | 自己的 `receipt_ref` 与 `raw_response_hash` |
| 账本面 | `opening_anchor` 加 `movements` 的重建 | 锚点版本，以及每笔变动自己的事件身份 |

账本面：

```text
opening_anchor    金额、资产、as_of、anchor_version
movements         带 §6 事件身份的有符号变动
reconstructed     = opening_anchor + 变动之和
```

锚点必须独立于账户快照。账本面的血缘若等于计价面或交易所权益面的血缘，判定为 `RECONCILE_NOT_INDEPENDENT`。把账户快照抄进账本面，同样是不独立。三面共用一个派生结果，不能算对账相符。

三面都已知且相互独立时，先用同一组钉住报价换成 BTC，再比较：

```text
max(三面) - min(三面) <= reconcile_tolerance_btc
```

容差必须是有限十进制，且大于或等于 `0`。缺失、`null`、非有限或负数：`TOLERANCE_INVALID`，政策不完整。差等于容差时相符。严格大于时 `RECONCILE_MISMATCH`。不挑选一面，不回写。

任一面未知：`RECONCILE_UNAVAILABLE`。两个未知不能配成相符。

---

## 9. 算术政策

`Decimal` 本身不保证乘除之后仍是有限小数。政策必须带上，并进入快照身份：

```text
arithmetic_policy_version
max_input_scale          非负整数
max_result_scale         非负整数
max_balance_rows         正整数
max_position_rows        正整数
max_event_rows           正整数
```

任一缺失或 `null`：`POLICY_INCOMPLETE`。超过行数上限：`RESOURCE_LIMIT`。

输入小数位多于 `max_input_scale`：`PRECISION_INSUFFICIENT`。乘法和除法的结果必须在 `max_result_scale` 位上精确落下，余数不为零则拒绝，不舍入后发布。加法只加这些已经精确的项。因此循环小数和放不下的长尾都使 `btc_nav` 为 `null`。同一政策重放，字节相同；换政策版本就是另一份身份。

---

## 10. 时间与绑定

`evaluation_at` 由调用方传入。历史重放使用这份时点，不读墙钟。时间文本只接受带 `Z` 或数字时区的形式。缺失、非法、无时区：`TIMESTAMP_INVALID`。

相对 `evaluation_at`：晚于评估时点为 `FUTURE_TIMESTAMP`；超过该输入的 SLA 为 `SLA_EXCEEDED`；组件 `as_of` 彼此之差超过错时上限为 `SKEW_EXCEEDED`。SLA 或错时上限为 `null`：`POLICY_INCOMPLETE`。相等不超过上限，严格大于才拒绝。

声明键是 `hash(source_claim, object, version_claim)`，不含 `evaluation_at`。纯函数把注入的 `binding_state` 与本次内容哈希比较：

| 注入状态 | 提案 |
|---|---|
| 该声明键不存在 | `APPEND`，并带回旧绑定原文 |
| 键存在且内容哈希相同 | `REPLAY` |
| 键存在且内容哈希不同 | `CONFLICT`，阻断 `INPUT_IDENTITY_CONFLICT` |

`CONFLICT` 的提案里旧哈希保持原样。只改 `evaluation_at` 不能把同版本的异内容变成 `APPEND`。

---

## 11. 阻断

任一阻断命中：

```text
btc_nav                 = null，除非 §5 允许的已知负净权益且没有其他阻断
account_authority       = NOT_ESTABLISHED
new_risk_usable         = false
reality_authority       = NOT_ESTABLISHED
order_intent            = ABSENT
```

负净权益是已知负数时可以留下这个负数，同时 `new_risk_usable` 仍为 false。其余阻断不发布净值。

| 代码 | 条件 |
|---|---|
| `ACCOUNT_IDENTITY_UNFIXED` | 身份缺字段，或 `account_ref` 为空 |
| `BINDING_STATE_ABSENT` | 未注入绑定历史 |
| `INPUT_IDENTITY_CONFLICT` | 注入状态中同版本内容不同 |
| `TIMESTAMP_INVALID` | 时间缺失、非法或缺时区 |
| `FUTURE_TIMESTAMP` | 时点晚于 `evaluation_at` |
| `SLA_EXCEEDED` | 超过该输入的 SLA |
| `SKEW_EXCEEDED` | 组件之间错时超过上限 |
| `UNSUPPORTED_PRODUCT` | 不是现货或 USDⓈ-M |
| `UNSUPPORTED_CONTRACT` | 不是线性永续，或乘数不是 `1` |
| `SET_INCOMPLETE` | 没有集合相等证明 |
| `DUPLICATE_ROW` | 资产或持仓身份重复 |
| `BALANCE_INCOMPLETE` | 缺行，或 free/locked 只出现一半 |
| `DOUBLE_COUNT` | free 与 total 同加，或已入钱包的流水再次扣加 |
| `TRANSFER_SCOPE_UNBALANCED` | 范围内划转净额不为 `0` |
| `SIGN_MISMATCH` | 余额为负，或负债行为负 |
| `NON_FINITE` | NaN、±Infinity，或非有限十进制 |
| `QUOTE_INVALID` | 报价为 `0` 或负数 |
| `QUOTE_UNPINNED` | 已知非零数量没有钉住报价 |
| `NOTIONAL_REJECTED` | 净值路径加入名义本金 |
| `WALLET_FLOW_BASIS_UNKNOWN` | 不能确定已结算流水是否已在钱包中 |
| `POSITION_UNKNOWN` | 持仓缺失或显式未知 |
| `POSITION_MALFORMED` | 持仓结构未通过验证 |
| `POSITION_MODE_UNKNOWN` | 衍生品缺持仓模式或保证金模式，或 HEDGE 腿无法归属 |
| `FEE_UNKNOWN` / `FUNDING_UNKNOWN` | 清单缺失，或空列表却没有零事件证明 |
| `FEE_INCOMPLETE` / `FUNDING_INCOMPLETE` | 分页、截断、保留范围或过滤范围未完成 |
| `EVENT_IDENTITY_CONFLICT` | 同一事件身份，正文不同 |
| `COLLECTION_PROOF_INVALID` | 证明缺字段或与账户绑定不一致 |
| `AUTHORITY_NOT_PROVABLE` | 自报权威，但本阶段不能建立现实权威 |
| `NAV_PARTIAL_REJECTED` | 用残缺组件或未钉住价格发布净值 |
| `RECONCILE_UNAVAILABLE` | 对账有一面未知 |
| `RECONCILE_NOT_INDEPENDENT` | 三面血缘不独立 |
| `RECONCILE_MISMATCH` | `max - min` 严格大于容差 |
| `SCOPE_MISMATCH` | 三面的账户、范围或计价时点不一致 |
| `TOLERANCE_INVALID` | 容差缺失、非有限或为负 |
| `PRECISION_INSUFFICIENT` | 输入超标度，或乘除不能在结果标度上精确落下 |
| `RESOURCE_LIMIT` | 超过政策中的行数上限 |
| `POLICY_INCOMPLETE` | SLA、错时、算术版本或上限缺失 |

---

## 12. 验收清单

这些测试在开工令出现之后才写。本文件不附带实现。夹具不访问网络，不打开真实账本。

| ID | 输入 | 期望 |
|---|---|---|
| AT-1 | 删掉 `account_ref` | `ACCOUNT_IDENTITY_UNFIXED`；`btc_nav=null` |
| AT-2 | 注入旧绑定后，同一版本余额不同 | `INPUT_IDENTITY_CONFLICT`；提案不替换旧哈希 |
| AT-3 | 新版本声明，注入状态只含旧版本 | `APPEND`；旧绑定原文仍在 |
| AT-4 | 缺 BTC 余额行 | `BALANCE_INCOMPLETE`；不用 `0` |
| AT-5 | BTC 余额显式 `0` | 该项为已知零；其他不完整项仍阻断净值 |
| AT-6 | 钱包余额为负 | `SIGN_MISMATCH` |
| AT-7 | `positions` 缺失 | `POSITION_UNKNOWN` |
| AT-8 | `positions="garbage"` | `POSITION_MALFORMED`；不是空仓 |
| AT-9 | 全部数量显式 `0` | 持仓 `FLAT`；不发出 `ACTIVE_CONFIRMED` |
| AT-10 | HEDGE 双腿都非零且无法归属 | `POSITION_MODE_UNKNOWN` |
| AT-11 | 费用清单缺失 | `FEE_UNKNOWN`；合计不是 `0` |
| AT-12 | 费用窗口分页未结束 | `FEE_INCOMPLETE` |
| AT-13 | funding 清单缺失 | `FUNDING_UNKNOWN`；不读 E0 默认 `0` |
| AT-14 | funding 保留范围截断 | `FUNDING_INCOMPLETE` |
| AT-15 | 非零 ETH 没有钉住的 BTC 报价 | `QUOTE_UNPINNED`；`btc_nav=null` |
| AT-16 | 用钱包数量乘未钉住价格 | `NAV_PARTIAL_REJECTED` |
| AT-17 | 组件中放入 NaN 或 ±Infinity | `NON_FINITE`；不先变成 `null` 再发布 |
| AT-18 | 合法 `null` 报价 | 保持 `null`；代码不是 `NON_FINITE` |
| AT-19 | 删掉 `as_of`、写成 `garbage`、写成无时区 | `TIMESTAMP_INVALID` |
| AT-20 | `as_of` 晚于 `evaluation_at` | `FUTURE_TIMESTAMP` |
| AT-21 | 超过 SLA；错时超过上限 | `SLA_EXCEEDED` 或 `SKEW_EXCEEDED` |
| AT-22 | SLA 为 `null` | `POLICY_INCOMPLETE` |
| AT-23 | 三面之一未知 | `RECONCILE_UNAVAILABLE` |
| AT-24 | 三面独立且 `max - min` 大于容差 | `RECONCILE_MISMATCH`；不回写 |
| AT-25 | `SYNTHETIC` 夹具要求权威 | `account_authority=NOT_ESTABLISHED`；`new_risk_usable=false` |
| AT-26 | 同一输入与同一算术政策重放 | 快照字节相同 |
| AT-27 | 静态扫描 | 无交易链导入，无真实账本路径，无 `datetime.now` / `time.time` |
| AT-28 | 钱包 `1000 USDT`，`0.1 BTC` 多头，开仓价等于标记价 `100000` | 未实现盈亏 `0`；权益 `1000 USDT`；不加 `0.1 BTC`。空头方向相反 |
| AT-29 | 手续费和 funding 已在钱包余额中，事件账再加一次 | `DOUBLE_COUNT`；净值不重复扣加 |
| AT-30 | 现货与合约钱包混加，或划转两侧只记入账 | `DOUBLE_COUNT` 或 `TRANSFER_SCOPE_UNBALANCED` |
| AT-31 | 无集合证明，或资产／持仓行重复 | `SET_INCOMPLETE` 或 `DUPLICATE_ROW`；不发布净值 |
| AT-32 | 全部输入自报 `AUTHORITATIVE`，证明缺失或与绑定不符 | `AUTHORITY_NOT_PROVABLE` 或 `COLLECTION_PROOF_INVALID`；权威不成立 |
| AT-33 | 分页失败、历史截断、有零事件证明的空窗口、清单缺失 | 分别为 `INCOMPLETE`、`INCOMPLETE`、已知零的 `COMPLETE`、`UNKNOWN` |
| AT-34 | 同事件身份异正文；不同 `event_type` 的相同 `stable_id`；迟到事件 | 冲突；两条都保留；新窗口版本且旧正文不变 |
| AT-35 | 同版本异内容只改 `evaluation_at`；绑定状态未注入 | 仍是 `CONFLICT`；缺注入时为 `BINDING_STATE_ABSENT`，不暗中写状态 |
| AT-36 | 三面血缘相同，或账本面抄账户快照 | `RECONCILE_NOT_INDEPENDENT` |
| AT-37 | 差等于容差；差大于容差；负容差；账户或时点不一致 | 相符；`MISMATCH`；`TOLERANCE_INVALID`；`SCOPE_MISMATCH` |
| AT-38 | `1/3` 一类循环小数；输入超过 `max_input_scale`；更换算术政策 | `PRECISION_INSUFFICIENT`；超标拒绝；字节随政策版本变化 |
| AT-39 | 负未实现盈亏；精确算出的负净权益；报价为 `0` 或负数 | 盈亏保持负数且不是 `SIGN_MISMATCH`；净权益保持负数；`QUOTE_INVALID` |

AT-26 使用记录中的 `evaluation_at`、钉住报价和 `arithmetic_policy_version`。更换墙钟不改变字节。

---

## 13. 明确不做

- 不实现本文件中的函数，不新增测试文件来冒充开工。
- 不修改 `aurora/risk_adjudicator.py`。
- 不修改 E2/E1，不重开 S1/S2/S3。
- 不接费用消费方，不接 funding，不读真实账户。
- 不迁移真实账本，不把事故副本演练写成已经独立验证。
- 不接 `trading_cycle`、`production_main`、旧 `RiskGate`。
- 不实现 P3-R3.2，不实现 P3-R4。
- 不解除 kill，不签发执行或部署许可。

若以后出现开工句，那一句只允许夹具上的纯函数和 §12 的测试。真实账户只读、隔离绑定层落地、账本迁移、消费方接线、裁决器接线、测试网写入，各自还要另签。

---

## 14. 台账

```text
P4 ACCOUNT TRUTH PLAN    = CHANGES-REQUIRED
P4 IMPLEMENTATION        = NOT AUTHORIZED
P3-R3.1                  = CLOSED / RUNTIME-PASS / READ-ONLY
S1 / S2 / S3             = CLOSED / OFFLINE PASS
真实账户／接线／迁移     = 未授权
LIVE / TESTNET WRITE     = NO-GO / DENIED
TRADING AUTHORITY        = UNCHANGED
```
