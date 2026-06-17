export default function RiskPanel({ risk }) {
  const statusColors = {
    SAFE: 'text-green-400',
    WARNING: 'text-yellow-400',
    CRITICAL: 'text-red-400'
  };

  const statusLabels = {
    SAFE: '风险可控',
    WARNING: '警告',
    CRITICAL: '危险'
  };

  const drawdownColor = risk.currentDrawdown > 5 ? 'text-red-400' : risk.currentDrawdown > 3 ? 'text-yellow-400' : 'text-green-400';
  const maxDrawdownColor = risk.maxDrawdown > 5 ? 'text-red-400' : risk.maxDrawdown > 3 ? 'text-yellow-400' : 'text-green-400';

  const dailyColor = risk.dailyPnl >= 0 ? 'text-green-400' : 'text-red-400';
  const weeklyColor = risk.weeklyPnl >= 0 ? 'text-green-400' : 'text-red-400';
  const totalColor = risk.totalPnl >= 0 ? 'text-green-400' : 'text-red-400';

  return (
    <div className="p-6 bg-gray-900 rounded-xl border border-gray-800">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-300">风险概览</h2>
        <span className={`font-bold ${statusColors[risk.status]}`}>
          {statusLabels[risk.status]}
        </span>
      </div>

      <div className="flex items-center justify-center mb-4">
        <div className="relative w-24 h-24">
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="48"
              cy="48"
              r="40"
              stroke="#2a2a3e"
              strokeWidth="8"
              fill="none"
            />
            <circle
              cx="48"
              cy="48"
              r="40"
              stroke={risk.status === 'SAFE' ? '#22c55e' : risk.status === 'WARNING' ? '#eab308' : '#ef4444'}
              strokeWidth="8"
              fill="none"
              strokeLinecap="round"
              strokeDasharray={`${risk.currentDrawdown * 10} 251`}
              className="transition-all duration-500"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold text-white">
              {risk.currentDrawdown.toFixed(1)}%
            </span>
            <span className="text-xs text-gray-400">当前回撤</span>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-400">当前回撤</span>
          <span className={`font-semibold ${drawdownColor}`}>
            {risk.currentDrawdown.toFixed(2)}%
          </span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-400">最大回撤</span>
          <span className={`font-semibold ${maxDrawdownColor}`}>
            {risk.maxDrawdown.toFixed(2)}%
          </span>
        </div>

        <div className="h-px bg-gray-800 my-2" />

        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-400">今日盈亏</span>
          <span className={`font-semibold ${dailyColor}`}>
            {risk.dailyPnl >= 0 ? '+' : ''}${risk.dailyPnl.toLocaleString()}
          </span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-400">本周盈亏</span>
          <span className={`font-semibold ${weeklyColor}`}>
            {risk.weeklyPnl >= 0 ? '+' : ''}${risk.weeklyPnl.toLocaleString()}
          </span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm text-gray-400">总盈亏</span>
          <span className={`font-semibold ${totalColor}`}>
            {risk.totalPnl >= 0 ? '+' : ''}${risk.totalPnl.toLocaleString()}
          </span>
        </div>
      </div>

      <button
        className="mt-4 w-full py-3 rounded-lg font-bold text-white bg-red-600 hover:bg-red-700 transition-colors"
        onClick={() => console.log('Kill switch activated')}
      >
        🔴 紧急停止
      </button>
    </div>
  );
}
