# AURORA - BTC Trading System

> 一个围绕 Bitcoin 构建的资本运行与风险控制系统

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        AURORA Production V1                      │
├─────────────────────────────────────────────────────────────────┤
│  Data Layer (Binance WebSocket + Redis Event Bus)               │
├─────────────────────────────────────────────────────────────────┤
│  Core Engine (State + Strategy + Position Sizing)               │
├─────────────────────────────────────────────────────────────────┤
│  Risk Management (Global Risk Engine + Kill Switch)             │
├─────────────────────────────────────────────────────────────────┤
│  Execution Layer (Idempotent Orders + Timeout)                  │
├─────────────────────────────────────────────────────────────────┤
│  Monitoring (Grafana + Telegram Alerts)                         │
└─────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 环境配置

```bash
cp .env.example .env
# 编辑 .env 填入你的配置
```

### 2. Docker 部署

```bash
docker-compose up -d
```

### 3. 本地运行

```bash
pip install -r requirements.txt
python main.py
```

## 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| Event Bus | `core/event_bus.py` | Redis Pub/Sub 事件总线 |
| Data Service | `services/data_service/` | Binance WebSocket 数据采集 |
| Strategy | `aurora/strategy_router.py` | 双引擎策略路由 |
| Risk Engine | `services/risk_service/` | 三层风控系统 |
| Execution | `services/execution_service/` | 幂等下单 + 超时管理 |
| Monitoring | `monitoring/` | 日志 + Telegram 报警 |

## 风控体系

- **账户层**: 最大杠杆、最大暴露
- **系统层**: 回撤限制、Kill Switch
- **市场层**: 波动率熔断、流动性检测

## 上线流程

详见 [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md)

1. 本地模拟测试
2. Binance Testnet
3. 压力测试
4. 小资金实盘 (7天)
5. 逐步放大

## 监控

- Grafana: http://localhost:3000
- Telegram: 配置 BOT_TOKEN 和 CHAT_ID

## 文档

- [部署指南](DEPLOYMENT.md)
- [上线 Checklist](LAUNCH_CHECKLIST.md)

## License

Private - All Rights Reserved