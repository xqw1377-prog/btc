export default function MarketPanel({ market }) {
  const regimeColors = {
    TREND: 'text-green-400',
    RANGE: 'text-yellow-400',
    TRANSITION: 'text-orange-400',
    LIQUIDITY_DRIVEN: 'text-purple-400'
  };

  const regimeLabels = {
    TREND: '趋势',
    RANGE: '震荡',
    TRANSITION: '过渡',
    LIQUIDITY_DRIVEN: '流动性'
  };

  const priceChangeColor = market.priceChange >= 0 ? 'text-green-400' : 'text-red-400';

  return (
    <div className="p-6 bg-gray-900 rounded-xl border border-gray-800">
      <h2 className="text-lg font-semibold mb-4 text-gray-300">市场状态</h2>

      <div className="mb-4">
        <div className="text-sm text-gray-400 mb-1">BTC/USDT</div>
        <div className="text-3xl font-bold text-white">
          ${market.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </div>
        <div className={`text-sm ${priceChangeColor}`}>
          {market.priceChange >= 0 ? '+' : ''}{market.priceChange.toLocaleString()} ({market.priceChangePercent >= 0 ? '+' : ''}{market.priceChangePercent}%)
        </div>
      </div>

      <div className="mb-4 p-3 bg-gray-800 rounded-lg">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-400">市场状态</span>
          <span className={`font-bold ${regimeColors[market.regime] || regimeColors.TREND}`}>
            {regimeLabels[market.regime] || '未知'}
          </span>
        </div>
        <div className="flex items-center">
          <span className="text-xs text-gray-500">置信度</span>
          <div className="flex-1 ml-2 h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full ${market.confidence > 0.7 ? 'bg-green-500' : market.confidence > 0.5 ? 'bg-yellow-500' : 'bg-red-500'}`}
              style={{ width: `${market.confidence * 100}%` }}
            />
          </div>
          <span className="text-xs text-gray-400 ml-2">{(market.confidence * 100).toFixed(0)}%</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400 mb-1">波动率</div>
          <div className="text-lg font-semibold text-white">{market.volatility.toFixed(2)}%</div>
        </div>

        <div className="p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400 mb-1">ATR</div>
          <div className="text-lg font-semibold text-white">{market.atr.toFixed(2)}</div>
        </div>

        <div className="p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400 mb-1">EMA 20/60</div>
          <div className="text-sm font-semibold text-white">
            {market.ema20 > market.ema60 ? '📈 多头' : '📉 空头'}
          </div>
        </div>

        <div className="p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400 mb-1">成交量</div>
          <div className="text-sm font-semibold text-white">
            {(market.volume / 1000).toFixed(0)}K
          </div>
        </div>
      </div>
    </div>
  );
}
