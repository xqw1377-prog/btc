# AURORA Production V1 - 部署指南

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    AURORA Production V1                      │
├─────────────────────────────────────────────────────────────┤
│  Data Layer                                                  │
│  ├── Binance WebSocket (Multi-stream)                       │
│  ├── Event Bus (Redis Pub/Sub)                              │
│  └── Data Normalization                                     │
├─────────────────────────────────────────────────────────────┤
│  Core Engine                                                 │
│  ├── Market State Engine (Hysteresis)                       │
│  ├── Strategy Router                                        │
│  ├── Position Sizing (V2)                                   │
│  └── Regime Learning                                        │
├─────────────────────────────────────────────────────────────┤
│  Risk Management                                             │
│  ├── Global Risk Engine                                     │
│  ├── Circuit Breakers                                       │
│  └── Kill Switch                                            │
├─────────────────────────────────────────────────────────────┤
│  Execution Layer                                             │
│  ├── Order Executor (Idempotent)                            │
│  ├── Order Verification                                     │
│  └── Timeout Management                                     │
├─────────────────────────────────────────────────────────────┤
│  Monitoring                                                  │
│  ├── Trade Logger                                           │
│  ├── Performance Monitor                                    │
│  └── Grafana Dashboard                                      │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 环境配置

```bash
# 复制环境配置
cp .env.example .env

# 编辑配置
nano .env
```

`.env` 配置内容:
```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
TESTNET=true
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 2. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 启动方式

#### 方式一：Docker 部署（推荐）

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f aurora

# 停止服务
docker-compose down
```

#### 方式二：本地运行

```bash
# 测试网模式
./start.sh testnet

# 或直接运行
python -m aurora.production_main
```

#### 方式三：生产模式

```bash
# 确保 .env 中 TESTNET=false
./start.sh live
```

## 核心组件说明

### 1. Event Bus (事件总线)

所有模块通过事件总线通信，支持 Redis Pub/Sub:

```python
from aurora.event_bus import EventBus, Event

# 订阅事件
event_bus.subscribe('kline', handler)

# 发布事件
await event_bus.publish(Event('kline', 'BTCUSDT', data))
```

### 2. Market State Engine V2

带滞回机制的状态识别，防止频繁切换:

```python
from aurora.market_state_engine_v2 import MarketStateEngineV2

engine = MarketStateEngineV2(confirmation_count=3)
state = engine.identify_regime(features)
# 需要连续3次确认才会切换状态
```

### 3. Global Risk Engine

三层风控体系:

```python
from aurora.global_risk_engine import GlobalRiskEngine

risk = GlobalRiskEngine()

# 验证交易
validation = risk.validate_trade(
    leverage=3.0,
    exposure_pct=0.1,
    position_size_pct=0.02,
    volatility=1.5,
    avg_volatility=1.0,
    spread_pct=0.001
)
```

### 4. Production Order Executor

幂等下单 + 超时管理:

```python
from aurora.production_order_executor import ProductionOrderExecutor

executor = ProductionOrderExecutor(client)

# 下单（自动去重）
result = executor.place_order(
    side='BUY',
    quantity=0.001,
    signal_type='TREND'
)

# 验证订单
executor.verify_order(result['client_id'])

# 检查超时
executor.check_timeouts()
```

## 监控

### Grafana Dashboard

访问 `http://localhost:3000`，默认密码: `aurora`

监控指标:
- 实时 PnL 曲线
- 胜率统计
- 持仓暴露
- 延迟监控
- 订单成交率

### 日志文件

```
logs/
├── trades.jsonl      # 交易记录
├── system.jsonl      # 系统事件
└── errors.jsonl      # 错误日志
```

## 回放系统

### 录制交易会话

```python
from aurora.replay_engine import ReplayEngine

engine = ReplayEngine()
engine.start_recording()
# ... 运行交易 ...
engine.stop_recording()
engine.save_recording("2024-01-15.json")
```

### 回放分析

```python
from aurora.replay_engine import replay_day

result = replay_day("2024-01-15")
print(result['analysis'])
```

## 风险控制

### Kill Switch

自动触发条件:
- 日内亏损 > 3%
- 最大回撤 > 10%
- 连续亏损 >= 5 次

手动重置:
```python
risk_engine.reset_kill_switch(manual=True)
```

### Circuit Breakers

- 波动率飙升
- 流动性下降
- 连接断开
- API 错误

## 生产检查清单

- [ ] API 权限配置正确（仅交易权限）
- [ ] IP 白名单设置
- [ ] 测试网充分测试
- [ ] 风控参数确认
- [ ] 监控告警配置
- [ ] 备份策略
- [ ] 断网恢复测试

## 故障排查

### 订单超时

检查网络连接和 API 限制:

```bash
# 查看订单状态
docker-compose logs aurora | grep "order"
```

### 状态抖动

调整 `confirmation_count`:

```python
engine = MarketStateEngineV2(confirmation_count=5)  # 增加确认次数
```

### 连接断开

WebSocket 自动重连，检查日志:

```bash
docker-compose logs -f aurora | grep "reconnect"
```

## 安全建议

1. **API 权限**: 仅开启交易权限，不要开启提现
2. **IP 白名单**: 限制 API 访问 IP
3. **资金隔离**: 使用独立账户
4. **定期审计**: 检查交易记录
5. **备份**: 定期备份配置和日志