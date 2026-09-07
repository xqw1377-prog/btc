# AURORA 能力台账（C6 登记）

> 本表是当前唯一能力真源。每条只写已核实状态；UNKNOWN / NOT-RUN
> 不因文档封存变成 PASS。

## 一、运行与授权

| 项 | 状态 | 证据 |
|---|---|---|
| PAPER 模式 | ACTIVE — 无交易所客户端、无出网 | tests/test_p0_safety.py, test_network_boundary.py |
| SHADOW 模式 | READ-ONLY TESTNET — 只读镜像，生产循环禁止实例化 | p0_boundary, test_production_entry_integrity |
| TESTNET 模式 | 武装路径存在；协议合同未完成（G0-4） | kernel + binance_exchange 映射测试 |
| LIVE 代码路径 | EXISTS（未被本批删除或改写） | production_main, safety.build_client |
| LIVE 授权条件 | 既有条件未修改：双重授权 + AURORA_ARM_LIVE | p0_boundary.assert_live_dual_auth / assert_not_live_trading |
| 当前 SDK+端点策略下的 armed-LIVE | BLOCKED_BEFORE_CLIENT — 构造期 spot ping 目标 api.binance.com 不在 ALLOWED_LIVE_HOSTS，授权齐全也构造前拒绝 | C2.1（04b2c0e），tests/test_network_boundary.py |
| 产品 LIVE 放行 | NOT-GRANTED | 本台账 |

**拒绝在 UNKNOWN 下开仓 ≠ 能够完成启动对账。**前者证明不继续增加
风险，后者证明能发现未知风险；两者不能互相替代。

## 二、执行内核与参考实现

| 项 | 状态 |
|---|---|
| aurora/kernel/ | 唯一生产执行内核（ADR-013） |
| aurora/execution_truth.py | TRACKED / OFFLINE_REFERENCE_ONLY；Decimal 记账与执行不变量保留参考价值；**不是**生产引擎、不得被生产导入、不证明生产正确性 |
| reference reconcile()/boot() | NOT-BUILT（本轮检查的当前仓库、可达 Git 历史及所检查的 quarantine 范围内，未找到可复用实现） |
| 生产导入隔离 | PASS — 静态扫描 + 干净子进程 sys.modules 检查 |
| 生产账本 Decimal 迁移 | NOT-DONE（仍 float/REAL；后续工作包） |

## 三、观察面

| 项 | 状态 |
|---|---|
| aurora/dashboard_feed.py | EXCHANGE_OBSERVATION / NOT_LEDGER_PROJECTION；只读白名单、分段时间戳、失败不伪装、回环 + Origin 白名单 |
| 浏览器行为验证 | NOT-RUN（vite build 通过 ≠ 浏览器呈现正确；BUILD_CONFIG_ISOLATION = NOT-EVIDENCED） |
| 保护单核验 | NOT_VERIFIED（本观察面不查条件单；G0-4 未完成前不得宣称已保护） |

## 四、已知未解决项（随基线封存的 OPEN 缺口）

| 工作包 | 保留任务 |
|---|---|
| G0-1 启动与持仓真相 | **BOOT-DRIFT**：无 intent 时的仓位漂移发现（exchange 有仓 & ledger 空 / 反向 / 查询失败 / 双空但有未决订单）；带仓恢复的 SL/TP 零值误平 |
| G0-2 确认计数 | 外层/内层按唯一已收盘 K 线去重 |
| G0-3 UNKNOWN 原则 | 既有修复已回归；保留性质级约束，不重造状态机 |
| G0-4 交易所协议 | Algo 单、HEDGE 模式核对、端点可用性、保护生命周期、错误码/限频/重试 |
| G0-5 生产隔离与配置 | `production_main` 裸 `load_dotenv()`（find_dotenv 隐式搜索）与自检配置来源一致性；退役包级依赖清理 |

沿用既有登记的 G1/G4/G5 迁移项（启动余额不刷新、死配置、数量精度、
内存移动止损、波动单位）不因未列入上表而消失。
