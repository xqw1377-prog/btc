# AURORA 实盘上线 Checklist

## 上线前总原则

- [ ] 系统不会因为异常"乱开单"
- [ ] 系统不会因为数据问题"重复下单"
- [ ] 系统不会因为亏损"失控加仓"

---

## Phase 1: 本地模拟测试

### 1.1 数据回放测试
- [ ] 使用过去30天BTC数据回放
- [ ] 确认无crash
- [ ] 验证信号输出一致性

### 1.2 状态机测试
- [ ] NEW → FILLED → CLOSED 流程
- [ ] PARTIAL → CANCELLED 流程
- [ ] 超时取消流程

### 1.3 单元测试
- [ ] FeatureEngine 测试通过
- [ ] MarketStateEngine 测试通过
- [ ] StrategyRouter 测试通过
- [ ] RiskEngine 测试通过

---

## Phase 2: Binance Testnet

### 2.1 连接测试
- [ ] WebSocket 连接成功
- [ ] 断线自动重连
- [ ] 数据补齐（gap fill）

### 2.2 下单测试
- [ ] 下单成功率 ≥ 99%
- [ ] 成交延迟 < 300ms
- [ ] Partial fill 正确处理
- [ ] 超时取消正常工作

### 2.3 风控测试
- [ ] Kill Switch 触发测试
- [ ] 日内止损测试
- [ ] 最大回撤测试
- [ ] 连续亏损测试

### 2.4 压力测试
- [ ] 模拟插针行情
- [ ] 模拟10%瞬时波动
- [ ] 模拟流动性骤降
- [ ] 验证不会乱开单
- [ ] 验证不会重复下单
- [ ] 验证不会爆仓

---

## Phase 3: 小资金实盘

### 3.1 资金准备
- [ ] 准备100-500 USDT
- [ ] API权限配置正确（仅交易权限）
- [ ] IP白名单设置

### 3.2 连续运行测试
- [ ] 运行 ≥ 7天
- [ ] 记录每日PnL
- [ ] 监控最大回撤
- [ ] 记录策略切换频率
- [ ] 记录execution错误率

### 3.3 风控指标验证
- [ ] 回撤 ≤ 5%
- [ ] 单日亏损 ≤ 2%
- [ ] 连亏 ≤ 5笔
- [ ] 系统错误率 ≤ 1%

---

## Phase 4: 系统稳定性

### 4.1 监控配置
- [ ] Grafana Dashboard 配置完成
- [ ] PnL曲线监控
- [ ] Drawdown监控
- [ ] Exposure监控
- [ ] Latency监控
- [ ] Win Rate监控

### 4.2 报警配置
- [ ] Telegram Bot 配置
- [ ] Kill Switch 报警
- [ ] Drawdown 报警
- [ ] API Error 报警
- [ ] Connection Loss 报警

### 4.3 回放验证
- [ ] 可以100%复现任意一天交易
- [ ] 包含signal, order, execution, pnl

---

## Phase 5: 资金放大

### 5.1 放大条件
- [ ] 小资金稳定 ≥ 7天
- [ ] Sharpe > 1
- [ ] Max DD < 5%
- [ ] Win Rate 稳定

### 5.2 放大流程
- [ ] Phase A: 初始资金稳定7天
- [ ] Phase B: 放大 ×2，再稳定7天
- [ ] Phase C: 放大 ×3，再稳定7天
- [ ] Phase D: 逐步放大至目标资金

---

## 上线成功标准

- [ ] 连续运行14天
- [ ] 无人工干预
- [ ] 无系统崩溃
- [ ] 回撤可控
- [ ] 可以复现PnL

---

## 故障预案

### API宕机
- [ ] 自动切换备用API
- [ ] 进入RISK_OFF状态
- [ ] 发送Telegram报警

### 极端行情
- [ ] Kill Switch自动触发
- [ ] 取消所有挂单
- [ ] 发送紧急报警

### 网络断开
- [ ] WebSocket自动重连
- [ ] 数据补齐机制
- [ ] 断线超过5分钟进入RISK_OFF

---

## 部署命令

```bash
# 1. 配置环境变量
cp .env.example .env
nano .env

# 2. 启动Docker服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f aurora

# 4. 停止服务
docker-compose down
```

---

## 最终确认

- [ ] 所有Phase测试通过
- [ ] 监控和报警配置完成
- [ ] 故障预案就绪
- [ ] 资金放大计划确认
- [ ] 上线签字确认