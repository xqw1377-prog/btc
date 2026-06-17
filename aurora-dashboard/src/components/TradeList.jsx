export default function TradeList({ trades }) {
  const getEngineColor = (engine) => {
    return engine === 'TREND' ? 'bg-blue-500' : 'bg-purple-500';
  };

  const getSideColor = (side) => {
    return side === 'BUY' ? 'text-green-400' : 'text-red-400';
  };

  const getSideLabel = (side) => {
    return side === 'BUY' ? '买入' : '卖出';
  };

  const getEngineLabel = (engine) => {
    return engine === 'TREND' ? '趋势' : '执行';
  };

  const getPnlColor = (pnl) => {
    return pnl >= 0 ? 'text-green-400' : 'text-red-400';
  };

  return (
    <div className="p-6 bg-gray-900 rounded-xl border border-gray-800">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-300">最近交易</h2>
        <button className="text-xs text-gray-400 hover:text-white">查看更多</button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs">
              <th className="text-left py-2">时间</th>
              <th className="text-left py-2">方向</th>
              <th className="text-left py-2">引擎</th>
              <th className="text-right py-2">入场价</th>
              <th className="text-right py-2">出场价</th>
              <th className="text-right py-2">数量</th>
              <th className="text-right py-2">盈亏</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-4 text-center text-gray-500">
                  暂无交易记录
                </td>
              </tr>
            ) : (
              trades.map((trade) => (
                <tr key={trade.id} className="border-t border-gray-800">
                  <td className="py-3 text-gray-400">
                    {new Date(trade.timestamp).toLocaleTimeString()}
                  </td>
                  <td className="py-3">
                    <span className={`font-medium ${getSideColor(trade.side)}`}>
                      {getSideLabel(trade.side)}
                    </span>
                  </td>
                  <td className="py-3">
                    <span className={`px-2 py-0.5 rounded text-xs text-white ${getEngineColor(trade.engine)}`}>
                      {getEngineLabel(trade.engine)}
                    </span>
                  </td>
                  <td className="py-3 text-right text-white">
                    ${trade.entryPrice.toLocaleString()}
                  </td>
                  <td className="py-3 text-right text-gray-400">
                    {trade.exitPrice ? `$${trade.exitPrice.toLocaleString()}` : '-'}
                  </td>
                  <td className="py-3 text-right text-white">
                    {trade.quantity.toFixed(4)}
                  </td>
                  <td className={`py-3 text-right font-semibold ${getPnlColor(trade.pnl)}`}>
                    {trade.pnl >= 0 ? '+' : ''}{trade.pnl.toFixed(2)}%
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
