import KLineChart from './components/KLineChart';
import useWS from './hooks/useWS';

function App() {
  // 统一通过 useWS hook 接入 WebSocket (带自动重连)，避免裸 WebSocket 断线后不恢复。
  const { system, market, risk, score, pnlData, trades, connected } = useWS();

  const formatUSD = (value) => {
    return (value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const getRegimeText = (regime) => {
    switch (regime) {
      case 'TREND': return '趋势';
      case 'RANGE': return '震荡';
      case 'TRANSITION': return '过渡';
      default: return '未知';
    }
  };

  const getRegimeColor = (regime) => {
    switch (regime) {
      case 'TREND': return '#3b82f6';
      case 'RANGE': return '#eab308';
      case 'TRANSITION': return '#6b7280';
      default: return '#6b7280';
    }
  };

  const getStatusText = (status) => {
    switch (status) {
      case 'SAFE': return '安全';
      case 'WARNING': return '警告';
      case 'DANGER': return '危险';
      default: return '未知';
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'SAFE': return '#22c55e';
      case 'WARNING': return '#eab308';
      case 'DANGER': return '#ef4444';
      default: return '#6b7280';
    }
  };

  const positions = system.positions || [];
  const hasPosition = positions.length > 0;
  const position = hasPosition ? positions[0] : null;
  const lastKline = market.klines?.[market.klines.length - 1] || {};

  return (
    <div style={{ minHeight: '100vh', background: '#0a0a0f', color: 'white', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Header */}
      <header style={{ background: '#111827', borderBottom: '1px solid #1f2937', padding: '12px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'linear-gradient(135deg, #22c55e, #3b82f6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', fontSize: '18px' }}>A</div>
            <div>
              <h1 style={{ fontSize: '18px', fontWeight: 'bold', background: 'linear-gradient(90deg, #22c55e, #3b82f6)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>AURORA</h1>
              <p style={{ fontSize: '11px', color: '#6b7280' }}>BTC 交易系统</p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '11px', color: '#6b7280' }}>BTC/USDT 永续合约</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                <span style={{ fontSize: '24px', fontWeight: 'bold' }}>${formatUSD(market.price)}</span>
                <span style={{ fontSize: '14px', color: market.priceChange >= 0 ? '#22c55e' : '#ef4444' }}>
                  {market.priceChange >= 0 ? '+' : ''}{market.priceChangePercent?.toFixed(2) || '0.00'}%
                </span>
              </div>
            </div>
            <div style={{ height: '40px', width: '1px', background: '#374151' }}></div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '11px', color: '#6b7280' }}>账户余额</div>
              <div style={{ fontSize: '18px', fontWeight: '600', color: '#22c55e' }}>${formatUSD(system.balance)}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: connected ? '#22c55e' : '#ef4444', animation: connected ? 'pulse 2s infinite' : 'none' }}></div>
              <span style={{ fontSize: '14px', color: '#9ca3af' }}>{connected ? '实时' : '离线'}</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main style={{ padding: '16px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: '16px' }}>
          {/* System Status */}
          <div style={{ gridColumn: 'span 3', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>系统状态</h3>
            <div style={{ background: '#059669', borderRadius: '10px', padding: '16px', color: 'white' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                <span style={{ fontSize: '14px', opacity: 0.8 }}>系统状态</span>
                <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: 'white', animation: 'pulse 2s infinite' }}></div>
              </div>
              <h1 style={{ fontSize: '24px', fontWeight: 'bold', marginBottom: '12px' }}>正常运行</h1>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontSize: '13px', opacity: 0.8 }}>引擎</span>
                <span style={{ fontWeight: '500' }}>趋势引擎</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontSize: '13px', opacity: 0.8 }}>持仓方向</span>
                <span style={{ fontWeight: '500', color: hasPosition ? (position.side === 'LONG' ? '#22c55e' : '#ef4444') : '#d1d5db' }}>
                  {hasPosition ? (position.side === 'LONG' ? '多头' : '空头') : '空仓'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontSize: '13px', opacity: 0.8 }}>持仓数量</span>
                <span style={{ fontWeight: '500' }}>{hasPosition ? `${position.size} BTC` : '0'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ fontSize: '13px', opacity: 0.8 }}>杠杆倍数</span>
                <span style={{ fontWeight: '500' }}>3x</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '13px', opacity: 0.8 }}>浮动盈亏</span>
                <span style={{ fontWeight: '500', color: (system.unrealizedPnl || 0) >= 0 ? '#22c55e' : '#ef4444' }}>
                  {hasPosition ? `${position.unrealizedPnl >= 0 ? '+' : ''}${formatUSD(position.unrealizedPnl)}` : '$0.00'}
                </span>
              </div>
            </div>
          </div>

          {/* KLine Chart */}
          <div style={{ gridColumn: 'span 6', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '14px', fontWeight: '500' }}>BTC/USDT</span>
                <span style={{ fontSize: '11px', color: '#6b7280' }}>永续合约</span>
                <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '4px', background: 'rgba(34, 197, 94, 0.2)', color: '#22c55e' }}>1分钟</span>
              </div>
              <div style={{ fontSize: '11px', color: '#6b7280' }}>{market.klines?.length || 0} 根K线</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '12px' }}>
              <span style={{ fontSize: '28px', fontWeight: 'bold' }}>${formatUSD(market.price)}</span>
              <span style={{ fontSize: '14px', color: market.priceChange >= 0 ? '#22c55e' : '#ef4444' }}>
                {market.priceChange >= 0 ? '+' : ''}{market.priceChange?.toFixed(2) || '0.00'} ({market.priceChangePercent >= 0 ? '+' : ''}{market.priceChangePercent?.toFixed(2) || '0.00'}%)
              </span>
            </div>
            <div style={{ height: '300px', background: '#1a1a2e', borderRadius: '8px', overflow: 'hidden' }}>
              <KLineChart marketData={market} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginTop: '12px' }}>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>开盘价</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>${formatUSD(lastKline.open)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>最高价</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>${formatUSD(lastKline.high)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>最低价</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>${formatUSD(lastKline.low)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>成交量</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{(lastKline.volume || 0).toFixed(2)}</div>
              </div>
            </div>
          </div>

          {/* Position */}
          <div style={{ gridColumn: 'span 3', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>持仓信息</h3>
            {hasPosition ? (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                  <span style={{ padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '500', background: position.side === 'LONG' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)', color: position.side === 'LONG' ? '#22c55e' : '#ef4444' }}>
                    {position.side === 'LONG' ? '多头' : '空头'}
                  </span>
                  <span style={{ fontSize: '18px', fontWeight: 'bold' }}>{position.size} BTC</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style={{ fontSize: '13px', color: '#6b7280' }}>开仓价格</span>
                  <span style={{ fontSize: '13px' }}>${formatUSD(position.entryPrice)}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span style={{ fontSize: '13px', color: '#6b7280' }}>浮动盈亏</span>
                  <span style={{ fontSize: '13px', color: position.unrealizedPnl >= 0 ? '#22c55e' : '#ef4444' }}>
                    {position.unrealizedPnl >= 0 ? '+' : ''}{formatUSD(position.unrealizedPnl)}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0' }}>
                <div style={{ fontSize: '14px', color: '#6b7280' }}>暂无持仓</div>
                <div style={{ fontSize: '12px', color: '#4b5563', marginTop: '4px' }}>等待交易信号...</div>
              </div>
            )}
            <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #1f2937' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', color: '#6b7280' }}>未实现盈亏</span>
                <span style={{ fontSize: '12px', color: system.unrealizedPnl >= 0 ? '#22c55e' : '#ef4444' }}>
                  {system.unrealizedPnl >= 0 ? '+' : ''}{formatUSD(system.unrealizedPnl)}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '12px', color: '#6b7280' }}>账户权益</span>
                <span style={{ fontSize: '12px' }}>${formatUSD(system.equity || system.balance)}</span>
              </div>
            </div>
          </div>

          {/* Market Analysis */}
          <div style={{ gridColumn: 'span 4', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>市场分析</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>市场状态</span>
              <span style={{ fontSize: '14px', fontWeight: '500', color: getRegimeColor(market.regime) }}>{getRegimeText(market.regime)}</span>
            </div>
            <div style={{ marginBottom: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', color: '#6b7280' }}>置信度</span>
                <span style={{ fontSize: '12px', color: '#9ca3af' }}>{((market.confidence || 0) * 100).toFixed(0)}%</span>
              </div>
              <div style={{ height: '6px', background: '#1f2937', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${(market.confidence || 0) * 100}%`, background: market.confidence > 0.7 ? '#22c55e' : market.confidence > 0.5 ? '#eab308' : '#ef4444', transition: 'width 0.5s' }}></div>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>波动率</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{(market.volatility || 0).toFixed(2)}%</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>ATR</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{(market.atr || 0).toFixed(2)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>趋势方向</div>
                <div style={{ fontSize: '13px', fontWeight: '500', color: market.ema20 > market.ema60 ? '#22c55e' : '#ef4444' }}>
                  {market.ema20 > market.ema60 ? '看涨' : '看跌'}
                </div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>成交量</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{market.volume ? (market.volume / 1000).toFixed(1) + 'K' : '0'}</div>
              </div>
            </div>
          </div>

          {/* Trade Score */}
          <div style={{ gridColumn: 'span 4', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>交易评分</h3>
            <div style={{ textAlign: 'center', marginBottom: '12px' }}>
              <div style={{ fontSize: '36px', fontWeight: 'bold', color: score >= 70 ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444' }}>
                {score}<span style={{ fontSize: '18px', color: '#6b7280' }}> / 100</span>
              </div>
              <div style={{ fontSize: '14px', color: score >= 70 ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444' }}>
                {score >= 70 ? '📈 适合交易' : score >= 50 ? '📊 谨慎交易' : '🔴 避免交易'}
              </div>
            </div>
            <div style={{ height: '8px', background: '#1f2937', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${score}%`, background: score >= 70 ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444', transition: 'width 0.5s' }}></div>
            </div>
          </div>

          {/* Risk Monitor */}
          <div style={{ gridColumn: 'span 4', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>风险监控</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>风险状态</span>
              <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '500', background: `${getStatusColor(risk.status)}20`, color: getStatusColor(risk.status) }}>{getStatusText(risk.status)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>今日盈亏</span>
              <span style={{ fontSize: '13px', color: (risk.dailyPnl || 0) >= 0 ? '#22c55e' : '#ef4444' }}>{(risk.dailyPnl || 0) >= 0 ? '+' : ''}{formatUSD(risk.dailyPnl)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>当前回撤</span>
              <span style={{ fontSize: '13px', color: risk.currentDrawdown > 5 ? '#ef4444' : risk.currentDrawdown > 2 ? '#eab308' : '#22c55e' }}>{(risk.currentDrawdown || 0).toFixed(2)}%</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>最大回撤</span>
              <span style={{ fontSize: '13px', color: '#9ca3af' }}>{(risk.maxDrawdown || 0).toFixed(2)}%</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>总盈亏</span>
              <span style={{ fontSize: '13px', color: (risk.totalPnl || 0) >= 0 ? '#22c55e' : '#ef4444' }}>{(risk.totalPnl || 0) >= 0 ? '+' : ''}{formatUSD(risk.totalPnl)}</span>
            </div>
          </div>

          {/* PnL Chart */}
          <div style={{ gridColumn: 'span 8', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>收益曲线</h3>
            <div style={{ height: '200px', background: '#1a1a2e', borderRadius: '8px', padding: '16px', overflow: 'hidden' }}>
              {pnlData.length > 0 ? (
                <svg width="100%" height="100%" viewBox="0 0 800 160" preserveAspectRatio="none">
                  {(() => {
                    const data = pnlData.slice(-50);
                    const values = data.map(d => d.pnl || 0);
                    const min = Math.min(...values, 0);
                    const max = Math.max(...values, 0.01);
                    const range = max - min || 1;
                    const points = values.map((v, i) => {
                      const x = (i / (values.length - 1)) * 800;
                      const y = 160 - ((v - min) / range) * 150;
                      return `${x},${y}`;
                    }).join(' ');
                    const zeroY = 160 - ((0 - min) / range) * 150;
                    return (
                      <>
                        <line x1="0" y1={zeroY} x2="800" y2={zeroY} stroke="#374151" strokeWidth="1" strokeDasharray="4,4" />
                        <polyline points={points} fill="none" stroke="#22c55e" strokeWidth="2" />
                        <polygon points={`0,160 ${points} 800,160`} fill="url(#pnlGradient)" />
                        <defs>
                          <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.3" />
                            <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
                          </linearGradient>
                        </defs>
                      </>
                    );
                  })()}
                </svg>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#6b7280' }}>
                  等待数据...
                </div>
              )}
            </div>
            {pnlData.length > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', fontSize: '12px', color: '#6b7280' }}>
                <span>最新: ${(pnlData[pnlData.length - 1]?.pnl || 0).toFixed(2)}</span>
                <span>数据点: {pnlData.length}</span>
              </div>
            )}
          </div>

          {/* Engine Status */}
          <div style={{ gridColumn: 'span 4', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>引擎状态</h3>
            <div style={{ marginBottom: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontSize: '13px', color: '#9ca3af' }}>趋势引擎</span>
                <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px', background: 'rgba(34, 197, 94, 0.2)', color: '#22c55e' }}>运行中</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '11px', color: '#6b7280', width: '50px' }}>置信度</span>
                <div style={{ flex: 1, height: '6px', background: '#1f2937', borderRadius: '3px', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${(market.confidence || 0) * 100}%`, background: '#3b82f6', transition: 'width 0.5s' }}></div>
                </div>
                <span style={{ fontSize: '11px', color: '#9ca3af', width: '32px' }}>{((market.confidence || 0) * 100).toFixed(0)}%</span>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
              <span style={{ fontSize: '13px', color: '#9ca3af' }}>市场状态</span>
              <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '11px', background: `${getRegimeColor(market.regime)}20`, color: getRegimeColor(market.regime) }}>{getRegimeText(market.regime)}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>EMA20</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>${formatUSD(market.ema20)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>EMA60</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>${formatUSD(market.ema60)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>ATR</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{(market.atr || 0).toFixed(2)}</div>
              </div>
              <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
                <div style={{ fontSize: '11px', color: '#6b7280' }}>ADX</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{(market.adx || 0).toFixed(1)}</div>
              </div>
            </div>
          </div>

          {/* Recent Trades */}
          <div style={{ gridColumn: 'span 12', background: '#111827', borderRadius: '12px', border: '1px solid #1f2937', padding: '16px' }}>
            <h3 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '12px' }}>最近交易</h3>
            {trades && trades.length > 0 ? (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: '13px', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ color: '#6b7280', borderBottom: '1px solid #1f2937' }}>
                      <th style={{ textAlign: 'left', padding: '8px 4px' }}>时间</th>
                      <th style={{ textAlign: 'left', padding: '8px 4px' }}>方向</th>
                      <th style={{ textAlign: 'right', padding: '8px 4px' }}>数量</th>
                      <th style={{ textAlign: 'right', padding: '8px 4px' }}>价格</th>
                      <th style={{ textAlign: 'right', padding: '8px 4px' }}>盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.slice(0, 10).map((trade, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #1f2937' }}>
                        <td style={{ padding: '8px 4px', color: '#9ca3af' }}>
                          {trade.timestamp ? new Date(trade.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'}
                        </td>
                        <td style={{ padding: '8px 4px' }}>
                          <span style={{ color: trade.side === 'BUY' ? '#22c55e' : '#ef4444', fontWeight: '500' }}>
                            {trade.side === 'BUY' ? '买入' : '卖出'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right', padding: '8px 4px', color: '#fff' }}>
                          {trade.quantity} BTC
                        </td>
                        <td style={{ textAlign: 'right', padding: '8px 4px', color: '#fff' }}>
                          ${formatUSD(trade.entryPrice)}
                        </td>
                        <td style={{ textAlign: 'right', padding: '8px 4px', fontWeight: '500', color: trade.pnl >= 0 ? '#22c55e' : '#ef4444' }}>
                          {trade.pnl >= 0 ? '+' : ''}{formatUSD(trade.pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#6b7280' }}>
                暂无交易记录
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer style={{ background: '#111827', borderTop: '1px solid #1f2937', padding: '8px 24px', marginTop: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#4b5563' }}>
          <div style={{ display: 'flex', gap: '16px' }}>
            <span>WebSocket: <span style={{ color: '#22c55e' }}>{connected ? '已连接' : '未连接'}</span></span>
            <span>数据源: Binance</span>
            <span>风险状态: <span style={{ color: getStatusColor(risk.status) }}>{getStatusText(risk.status)}</span></span>
          </div>
          <span>AURORA v1.0.0 | 仅BTC</span>
        </div>
      </footer>
    </div>
  );
}

export default App;