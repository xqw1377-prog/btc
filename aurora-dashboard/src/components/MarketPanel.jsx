export default function MarketPanel({ market }) {
  const regimeColors = {
    TREND: 'text-blue-400',
    RANGE: 'text-yellow-400',
    TRANSITION: 'text-gray-400'
  };

  const regimeLabels = {
    TREND: '趋势行情',
    RANGE: '震荡行情',
    TRANSITION: '过渡阶段'
  };

  const formatValue = (value, decimals = 2) => {
    return (value || 0).toFixed(decimals);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">市场状态</span>
        <span className={`text-sm font-medium ${regimeColors[market.regime] || 'text-gray-400'}`}>
          {regimeLabels[market.regime] || '未知'}
        </span>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">置信度</span>
          <span className="text-xs text-gray-400">{((market.confidence || 0) * 100).toFixed(0)}%</span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ${
              market.confidence > 0.7 ? 'bg-green-500' : 
              market.confidence > 0.5 ? 'bg-yellow-500' : 'bg-red-500'
            }`}
            style={{ width: `${(market.confidence || 0) * 100}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="bg-gray-800 rounded-lg p-2">
          <div className="text-xs text-gray-500 mb-1">波动率</div>
          <div className="text-sm font-medium">{formatValue(market.volatility)}%</div>
        </div>

        <div className="bg-gray-800 rounded-lg p-2">
          <div className="text-xs text-gray-500 mb-1">ATR</div>
          <div className="text-sm font-medium">{formatValue(market.atr)}</div>
        </div>

        <div className="bg-gray-800 rounded-lg p-2">
          <div className="text-xs text-gray-500 mb-1">趋势方向</div>
          <div className="text-sm font-medium">
            {market.ema20 > market.ema60 ? (
              <span className="text-green-400">看涨</span>
            ) : (
              <span className="text-red-400">看跌</span>
            )}
          </div>
        </div>

        <div className="bg-gray-800 rounded-lg p-2">
          <div className="text-xs text-gray-500 mb-1">成交量</div>
          <div className="text-sm font-medium">
            {market.volume ? (market.volume / 1000).toFixed(1) + 'K' : '0'}
          </div>
        </div>
      </div>
    </div>
  );
}