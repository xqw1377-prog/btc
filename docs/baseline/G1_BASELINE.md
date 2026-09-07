# G-1 基线封存记录（C6）

> 本记录冻结的是**准确、可追溯的当前基线**，不是"所有 G0 缺陷已修完"。
> 封存 ≠ 生产安全放行；已知缺口随基线一并登记、保持 OPEN。

## 一、代码身份

- 分支：`safety/p0a-mainnet-isolation`
- 代码证据基点：`0bdde2a`（C5，最后一个代码/测试提交）
- 提交链：

```text
bc7c8e6  G-1/C1  秘密与运行产物隔离（.dockerignore ×2 + .gitignore WAL/SHM）
bbd191a  G-1/C2  端点与构造期出站边界
04b2c0e  G-1/C2.1 首跳正向白名单 + 传输边界强制禁重定向
987cdd3  G-1/C3  ADR-013 reference 归属收口
d4d79d3  G-1/C4  safety_check 显式配置来源 + 零执行能力
0bdde2a  G-1/C5  dashboard 只读观察面收口
<C6>     G-1/C6  本文档批（提交哈希见提交回报，不在文档内预填）
```

## 二、ADR 登记

- **ADR-013**：`aurora/kernel/` 唯一生产执行内核；`aurora/execution_truth.py`
  TRACKED / OFFLINE_REFERENCE_ONLY；生产导入 reference 禁止；quarantine
  模块不恢复；reference 测试不构成生产安全性证明。
- **ADR-014（现行 LIVE 能力边界）**：LIVE 代码路径存在；授权条件未变；
  在当前 SDK 1.0.19 + 端点策略下，armed-LIVE 于构造前被阻断
  （api.binance.com 不在 ALLOWED_LIVE_HOSTS）；产品 LIVE 放行 NOT-GRANTED。
- reference reconcile/boot：NOT-BUILT。缺失模块表述限定为：
  "本轮检查的当前仓库、可达 Git 历史及所检查的 quarantine 范围内，
  未找到可复用实现。"

## 三、环境身份

```text
Python            3.9.6 (/usr/bin/python3)
python-binance    1.0.19
requests          2.31.0
python-dotenv     1.0.0
pytest            7.4.4 + hypothesispytest（显式 -p 加载）
hypothesis        6.141.1 / numpy 1.26.3 / pandas 2.1.4（本机实际版本；
                  requirements 声明 1.26.4 / 2.2.2，无锁文件）
```

测试命令（固定口径，无临时排除）：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest -p hypothesispytest --collect-only -q tests/
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -m pytest -p hypothesispytest -ra tests/
```

## 四、证据身份

- 最近一次全树：**239 collected / 239 passed**（数字随提交演进，不作
  封存门槛）。
- 收集清单与插件轨迹：`docs/baseline/pytest_collected_C3.txt`、
  `pytest_trace_config_C3.txt`（C3 时点快照）。
- 传输边界证据：`tests/test_network_boundary.py`（真实 SDK 构造 +
  HTTPAdapter spy，零真实出网）。
- 只读观察证据：`tests/test_dashboard_feed.py`（含本机回环 Origin
  握手，假数据，测后关闭）。
- reference 归属与逐断言映射：
  `docs/baseline/reference_tests/DISPOSITION.md` + 归档原件 `.txt`。

## 五、未解决项（随基线封存，保持 OPEN）

```text
BOOT-DRIFT (G0-1)     REQUIRED_UNCOVERED — 无 intent 的仓位漂移发现
G0-4                  PENDING — Algo/HEDGE/保护生命周期/协议证据
G0-5                  OPEN — 生产入口 load_dotenv 隐式搜索与自检一致性
ShadowRunner          NOT-BUILT / NOT-COVERED
BOOT 对账             reference 侧 NOT-BUILT；kernel 仅 per-intent 恢复
Decimal 账本迁移       NOT-DONE
Docker 镜像层验证      NOT-RUN（本机无 docker CLI）
历史凭证暴露处置       OPEN（C1 仅阻断未来打包，不处置历史）
干净环境复现           NOT-RUN（无锁文件）
浏览器行为验证         NOT-RUN
BUILD_CONFIG_ISOLATION NOT-EVIDENCED（vite 构建未做环境隔离验证）
```

## 六、现场与权限声明

- 未修改 `.env`、未停止运行程序、未动账户；不声称真实进程状态。
- 无真实交易所网络调用；无 Docker build/push；未推送任何提交。
- 敏感信息：本记录不含真实 `.env`、密钥、token、运行数据库或原始
  账户响应。

```text
G-1_BASELINE                  SEALED（以代码基点 0bdde2a + 本记录）
G0_EXECUTION_QUALIFICATION    NOT-GRANTED
LIVE                          NO-GO
```
