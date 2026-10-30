# P4 权威账户真相 — 纯文档方案

Status: `DOCUMENT CANDIDATE / IMPLEMENTATION NOT AUTHORIZED`  
Date: `2026-10-30`

```text
本文件 = 账户身份、余额／负债、持仓、费用与 funding 完整性、
         BTC NAV 计价、对账规则，以及未知／过期时的阻断清单
本文件 ≠ 开工令
本文件 ≠ 账户权威已经建立
本文件 ≠ 执行资格

P3-R3.1                  = CLOSED / RUNTIME-PASS / READ-ONLY
EXECUTION ELIGIBILITY    = DENIED
LIVE                     = NO-GO
REAL TESTNET WRITE       = DENIED
TRADING AUTHORITY        = UNCHANGED
EXECUTE_AUTHORIZED       = FALSE
KILL / INCIDENT_LOCK     = 不解除

E2 / E1                  = FROZEN（本方案不改常数、不改身份）
S1 / S2 / S3             = CLOSED / OFFLINE PASS（关闭不等于消费方可以接线）
费用投影消费方 / funding = HOLD / 未授权
真实账本迁移             = NOT AUTHORIZED
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

## 0. 这一刀要冻结什么

以后若单独获准实现，只允许有一个纯函数：

```text
evaluate_account_truth(
    identity,
    balances,
    positions,
    fees,
    funding,
    quotes,
    ledger_aggregate,
    policy,
    evaluation_at,
) -> AccountTruthSnapshot
```

函数吃进已经版本化的组件，吐出一份可重放的快照。它不拉行情，不读墙钟，不写账本，不下单。

快照要同时回答六件事：

1. 这是哪一个账户。
2. 余额和负债是否每项都已知。
3. 持仓结构是否经过验证。
4. 费用和 funding 在声明的窗口里是否完整。
5. BTC NAV 能否由这些组件按同一套计价规则重算。
6. 各面是否对得上；对不上时整份净值保持未知。

任一必填项未知、过期、畸形或对不上，整份 `btc_nav` 为未知，`account_authority` 为 `NOT_ESTABLISHED`，`new_risk_usable` 为 false。缺项保持缺项，不用 `0` 填上。

---

## 1. 明确不回答

- 不证明保护已经 `ACTIVE_CONFIRMED`。保护与退出恢复仍是后一张工单。
- 不证明可以下单。`execution_eligibility` 保持 `DENIED`，`order_intent` 保持 `ABSENT`。
- 不把账户未知折叠成整张决策卡未知。目标候选可以仍然存在；当前账户与增量可以分别未知。
- 不计算是否跑赢 BTC HODL，不产出 Excess BTC。
- 不把 E0 的 quote 权益当成 BTC NAV。E0 的 `funding_paid` 默认值不是“已知资金费为零”。
- 不把 S3 的离线费用投影当成交易所已经确认的费用。
- 不把 funding 模块“已实现但未接线”当成窗口已经完整。
- 不修改 E2/E1，不重开 S1/S2/S3。

---

## 2. 快照形状

```text
account_authority     ESTABLISHED | NOT_ESTABLISHED
new_risk_usable       false | true          # 只有 ESTABLISHED 才能为 true
btc_nav               十进制文本 | null
btc_nav_unit          BTC | null
btc_nav_trace         组件清单 | null
balances              已验证清单 | null
liabilities           已验证清单 | null
positions             FLAT | KNOWN | UNKNOWN | MALFORMED
fees                  COMPLETE | INCOMPLETE | UNKNOWN
funding               COMPLETE | INCOMPLETE | UNKNOWN
reconciliation        MATCH | MISMATCH | UNAVAILABLE
blockers              代码列表
source                SYNTHETIC | UNVERIFIED | AUTHORITATIVE
as_of
evaluation_at
identity_version
canonical_version     aurora-canonical-json-v1
hash_alg              sha256
```

`null`、空串、缺失键都是未知。显式的十进制 `0` 才是已知的零。

`source=AUTHORITATIVE` 只有在每一项必填组件自身都是 `AUTHORITATIVE`、完整性谓词全部成立、对账为 `MATCH` 时才能出现。`status=KNOWN`、`freshness=ok`、调用方自报 `AUTHORITATIVE`，都不能单独升级来源。夹具只能是 `SYNTHETIC`。`SYNTHETIC` 可以生成供测试阅读的快照，读起来仍然不是当前实盘资格。

在本方案获准实现并独立通过之前，R3.1 记录上的 `account_authority` 继续是 `NOT_ESTABLISHED`。本方案不修改裁决器。

规范化沿用 R3.1 已冻结的 `aurora-canonical-json-v1` 与 `sha256`。数字只以十进制文本出现。不另起一套哈希。

身份沿用同一条声明规则：`declaration_key = hash(source, object, version_claim)` 首次绑定 `content_hash`。同声明异内容拒绝，不覆盖旧绑定。合法新版本是版本声明本身变了。只改 `evaluation_at` 不能把一份已冲突的内容变成新快照。

---

## 3. 账户身份

一份账户至少要有：

```text
venue
account_ref          不透明引用，不是密钥，不是 API key
market_mode          SPOT | ONE_WAY | HEDGE
account_version
source
as_of
```

`account_ref` 缺失、为空，或看起来像密钥材料：身份不能固定，快照拒绝。仓库和方案正文不放真实账户编号，也不放密钥。

`market_mode` 缺失时，现货余额仍可逐项标注；只要存在任何衍生品持仓，整份持仓为 `POSITION_MODE_UNKNOWN`，净值未知。`HEDGE` 下同一合约两侧都非零时，持仓为未知，不合并成一条净额。

同一 `account_version` 下身份正文不同：`INPUT_IDENTITY_CONFLICT`。不另写一条“权威”快照。

---

## 4. 余额与负债

余额和负债分开列。每一行是：

```text
asset
amount          十进制，负债行表示欠下的数量，必须 ≥ 0
unit            与 asset 一致
status          KNOWN
```

规则：

- 缺这一行，表示该资产未知，不是 `0`。
- 显式 `0` 且 `status=KNOWN`，才是已知的零余额或已知无负债。
- 余额行出现负数：`SIGN_MISMATCH`。负债不靠负数余额暗中表达。
- 负债行出现负数：`SIGN_MISMATCH`。
- 非有限数：`NON_FINITE`。不改写成 `null` 再继续。
- 资产集合不完整，而调用方又把整包标成 `KNOWN`：`BALANCE_INCOMPLETE`。
- 保证金若已经含在钱包余额里，不再加一次。两边是否重叠无法判定：`OVERLAP_UNRESOLVED`，净值未知。

---

## 5. 持仓

持仓不是余额。现货 BTC 在余额里；BTCUSDT 永续在持仓里。没有标签就把两边相加，结构无效。

只有下面两种结构可以标成已知或空仓：

- `FLAT`：持仓列表为空，或每个数量字段都是显式十进制 `0`，且 `status=KNOWN`。
- `KNOWN`：`status=KNOWN`，每个数量都是有限十进制，合约、方向和 `market_mode` 齐全。

此外：

- 缺键、`null`、空串、`UNKNOWN`：`UNKNOWN`。
- 字符串、缺数量、数量非十进制：`MALFORMED`。
- `MALFORMED` 不是空仓，也不是已确认的持仓。
- 本模块不发出 `ACTIVE_CONFIRMED`。调用方带来的保护标签只记为 `claimed_protection`，原样保留，不升级。

空仓只说明现有仓位数量为零。它不取消后续工单里对拟新增仓位的保护要求。

---

## 6. 费用与 funding 完整性

完整性是窗口谓词，不是“有一个数字”。

窗口必须自带时区明确的 `window_from` 与 `window_to`，并且每个事件有稳定标识。同一标识重放不改变合计。合计是事件十进制金额之和。

| 观察 | 判定 |
|---|---|
| 整包缺失 | `UNKNOWN` |
| 窗口缺边、事件缺稳定标识、窗口内有缺口 | `INCOMPLETE` |
| 事件齐全、重放合计不变 | `COMPLETE` |
| 晚到事件 | 新版本，不改旧窗口的已绑定正文 |

`UNKNOWN` 与 `INCOMPLETE` 都使净值未知。禁止把它们记成 `0`。

S3 费用投影保持 `CLOSED / OFFLINE PASS`。投影可以在以后的只读测试里当作一个离线组件引用；投影缺失仍是不完整。投影行不是交易所确认。本方案不授权费用消费方接线。

funding 维持“模块已实现、未接线”。未取到的 funding 是 `UNKNOWN`。没有稳定 `tranId` 的事件拒收，并且该窗口不完整。`PARTIAL_LATE` 保持部分，不因时间过去而变成完整。E0 列上的 `funding_paid` 默认 `0` 不得被读成已知的零。本方案不授权 funding 接线。

---

## 7. BTC NAV 计价

单位是 BTC。净值是一条可重放的组件迹，不是单个二进制浮点。

在全部必填组件已知、报价已钉住、重叠已排除时，计价是：

```text
btc_nav =
    btc_balance
  - btc_liability
  + 每个已验证衍生品的数量 × 该合约钉住的 BTC 报价
  + 每个非 BTC 现货余额 × 该资产钉住的 BTC 报价
  - 每个非 BTC 负债 × 同一钉住报价
```

报价来自这次输入里的 `quote_version`，不在函数内部另取一口价。重放使用快照里记下的报价。

下面任一成立，整份 `btc_nav` 为 `null`，不输出部分和：

- 任一必需数量、负债或报价未知、过期、畸形或非有限。
- 已知非零数量缺少对应的钉住报价。
- 已知为零的数量不需要报价。
- 数量未知时，即使报价存在，净值仍未知。
- 用钱包数量乘上未钉住的最新价拼出一个净值。
- 把 quote 权益、USDT 盈亏或 E0 `equity` 直接标成 BTC NAV。
- 未实现盈亏已经含在盯市数量里，又再加一遍。重叠无法拆开时，净值未知。

钉住报价自身过期或缺失时，不沿用上一口价。

---

## 8. 对账

三面都已知时才比较：

1. 本节计价得到的 `btc_nav`。
2. 交易所报告的权益，经同一组钉住报价换成 BTC。
3. 账本聚合，经同一组钉住报价换成 BTC，且账本窗口与账户 `as_of` 的错时不超过政策上限。

任一面对未知：`RECONCILE_UNAVAILABLE`。两个未知不能配成相符。

三面都已知，且绝对差大于政策里的 `reconcile_tolerance_btc`：`RECONCILE_MISMATCH`。不挑选较大的一面，不回写账本，不自动修差异。

`reconcile_tolerance_btc` 必须是有限十进制。缺失或 `null`：政策不完整，失败关闭。本方案不规定具体容差值。

对账相符仍只说明这三面在该容差内一致。它不证明保护有效，也不证明可以下单。

---

## 9. 时间与过期

`evaluation_at` 由调用方传入，进入内容身份。历史重放读快照里的 `evaluation_at`，不读墙钟。

账户、报价、费用窗口、funding 窗口和账本聚合的时间，只接受带 `Z` 或数字时区的文本。缺失、非法、无时区：`TIMESTAMP_INVALID`。不跳过时效检查，也不以未处理异常代替快照。

相对 `evaluation_at`：

- `as_of` 晚于评估时点：`FUTURE_TIMESTAMP`。
- 超过该输入在政策中的 SLA：`SLA_EXCEEDED`。
- 各 `as_of` 彼此之差超过政策中的错时上限：`SKEW_EXCEEDED`。
- SLA 或错时上限为 `null`：政策不完整。不发明默认时限。

相等不超过上限。严格大于才拒绝。

---

## 10. 未知或过期时的阻断

快照在下列任一命中时：

```text
btc_nav            = null
account_authority  = NOT_ESTABLISHED
new_risk_usable    = false
order_intent       = ABSENT
```

防守意图若由调用方标出，原样保留在快照说明里。本模块不计算减仓数量，也不发出平仓指令。

阻断代码按第一次命中的类别保留，其余命中列入 `blockers`，不互相覆盖：

| 代码 | 条件 |
|---|---|
| `ACCOUNT_IDENTITY_UNFIXED` | 身份缺字段，或 `account_ref` 为空 |
| `INPUT_IDENTITY_CONFLICT` | 同一版本声明，内容不同 |
| `TIMESTAMP_INVALID` | 时间缺失、非法或缺时区 |
| `FUTURE_TIMESTAMP` | 时点晚于 `evaluation_at` |
| `SLA_EXCEEDED` | 超过该输入的 SLA |
| `SKEW_EXCEEDED` | 组件之间错时超过上限 |
| `BALANCE_INCOMPLETE` | 标成已知的资产集合缺行 |
| `SIGN_MISMATCH` | 余额为负，或负债行为负 |
| `NON_FINITE` | NaN、±Infinity，或非有限十进制 |
| `OVERLAP_UNRESOLVED` | 保证金、未实现盈亏与余额的重叠无法拆开 |
| `POSITION_UNKNOWN` | 持仓缺失或显式未知 |
| `POSITION_MALFORMED` | 持仓结构未通过验证 |
| `POSITION_MODE_UNKNOWN` | 有衍生品但保证金模式未知，或 HEDGE 双腿无法归属 |
| `FEE_UNKNOWN` | 费用包缺失 |
| `FEE_INCOMPLETE` | 费用窗口有缺口或缺稳定标识 |
| `FUNDING_UNKNOWN` | funding 包缺失，或未取到 |
| `FUNDING_INCOMPLETE` | 窗口不完整、缺 `tranId`，或仍是 `PARTIAL_LATE` |
| `QUOTE_UNPINNED` | 非零数量没有钉住的 BTC 报价 |
| `NAV_PARTIAL_REJECTED` | 试图用残缺组件发布净值 |
| `RECONCILE_UNAVAILABLE` | 对账有一面未知 |
| `RECONCILE_MISMATCH` | 三面已知但超出容差 |
| `POLICY_INCOMPLETE` | 容差、SLA 或错时上限缺失 |
| `SOURCE_NOT_AUTHORITATIVE` | 调用方要求权威，但组件来源不足 |

删除某条路径清单或自报字段，不能绕过已经写在组件上的非有限标记、缺失标记或来源标记。

---

## 11. 以后实现时的验收清单

这些测试在开工令出现之后才写。本文件不附带实现。每条都要在夹具上失败关闭，并且不访问网络、不打开真实账本。

| ID | 输入 | 期望 |
|---|---|---|
| AT-1 | 删掉 `account_ref` | `ACCOUNT_IDENTITY_UNFIXED`；`btc_nav=null` |
| AT-2 | 同一 `account_version`，余额不同 | `INPUT_IDENTITY_CONFLICT`；不覆盖旧快照 |
| AT-3 | 版本声明与余额一起换成新版本 | 新快照；旧快照字节不变 |
| AT-4 | 缺 BTC 余额行 | `BALANCE_INCOMPLETE`；不用 `0` |
| AT-5 | BTC 余额显式 `0` | 该项为已知零；其他不完整项仍阻断净值 |
| AT-6 | 余额为负 | `SIGN_MISMATCH` |
| AT-7 | `positions` 缺失 | `POSITION_UNKNOWN` |
| AT-8 | `positions="garbage"` | `POSITION_MALFORMED`；不是空仓 |
| AT-9 | 全部数量显式 `0` | 持仓 `FLAT`；保护标签不被升级成 `ACTIVE_CONFIRMED` |
| AT-10 | HEDGE 双腿都非零且无法归属 | `POSITION_MODE_UNKNOWN` |
| AT-11 | 费用包缺失 | `FEE_UNKNOWN`；合计不是 `0` |
| AT-12 | 费用窗口缺一条稳定标识 | `FEE_INCOMPLETE` |
| AT-13 | funding 未取到 | `FUNDING_UNKNOWN`；不读 E0 默认 `0` |
| AT-14 | funding 为 `PARTIAL_LATE` | `FUNDING_INCOMPLETE` |
| AT-15 | 非零 ETH 没有钉住的 BTC 报价 | `QUOTE_UNPINNED`；`btc_nav=null` |
| AT-16 | 只用钱包数量乘未钉住价格 | `NAV_PARTIAL_REJECTED` |
| AT-17 | 组件里放入 NaN 或 ±Infinity | `NON_FINITE`；不落成 `null` 后继续发布净值 |
| AT-18 | 合法 `null` 报价 | 保持 `null`；代码不是 `NON_FINITE` |
| AT-19 | 删掉 `as_of`、写成 `garbage`、写成无时区 | `TIMESTAMP_INVALID`；不抛未处理异常 |
| AT-20 | `as_of` 晚于 `evaluation_at` | `FUTURE_TIMESTAMP` |
| AT-21 | 超过 SLA；错时超过上限 | `SLA_EXCEEDED` 或 `SKEW_EXCEEDED` |
| AT-22 | SLA 为 `null` | `POLICY_INCOMPLETE` |
| AT-23 | 三面之一未知 | `RECONCILE_UNAVAILABLE` |
| AT-24 | 三面已知且差额大于容差 | `RECONCILE_MISMATCH`；不回写 |
| AT-25 | 组件为 `SYNTHETIC`，调用方要求权威 | `SOURCE_NOT_AUTHORITATIVE`；`account_authority=NOT_ESTABLISHED` |
| AT-26 | 同一完整夹具重放 | 快照字节相同 |
| AT-27 | 静态扫描 | 无交易链导入，无真实账本路径，无 `datetime.now` / `time.time` |

AT-26 的字节比较使用记录下来的 `evaluation_at` 与钉住报价。更换墙钟不得改变字节。

---

## 12. 明确不做

- 不实现本文件中的函数，不新增测试文件来冒充开工。
- 不修改 `aurora/risk_adjudicator.py`，不把快照接进裁决器。
- 不修改 E2/E1，不重开 S1/S2/S3。
- 不接费用消费方，不接 funding。
- 不迁移真实账本，不把事故副本演练写成已经独立验证。
- 不读真实账户，不发测试网或主网请求。
- 不接 `trading_cycle`、`production_main`、旧 `RiskGate`。
- 不实现 P3-R3.2，不实现 P3-R4。
- 不解除 kill，不签发执行或部署许可。
- 不把本方案写成 `P3 COMPLETE`、`TRADING GO` 或 `LIVE GO`。

若以后出现开工句，那一句只允许夹具上的纯函数和 §11 的测试。真实账户只读、账本迁移、消费方接线、裁决器接线、测试网写入，各自还要另签。

---

## 13. 台账

```text
P4 ACCOUNT TRUTH PLAN    = DOCUMENT CANDIDATE / IMPLEMENTATION NOT AUTHORIZED
P3-R3.1                  = CLOSED / RUNTIME-PASS / READ-ONLY
EXECUTION ELIGIBILITY    = DENIED
S1 / S2 / S3             = CLOSED / OFFLINE PASS
R3.2 / P3-R4             = HOLD / NOT AUTHORIZED
账户真源、费用消费方、funding 接线 = 未授权
真实账本迁移             = NOT AUTHORIZED
LIVE / TESTNET WRITE     = NO-GO / DENIED
TRADING AUTHORITY        = UNCHANGED
```
