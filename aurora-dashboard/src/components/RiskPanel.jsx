export default function RiskPanel({ risk }) {
  const getStatusConfig = (status) => {
    switch (status) {
      case 'SAFE':
        return { color: 'text-green-400', bg: 'bg-green-500/20', label: '安全' };
      case 'WARNING':
        return { color: 'text-yellow-400', bg: 'bg-yellow-500/20', label: '警告' };
      case 'DANGER':
        return { color: 'text-red-400', bg: 'bg-red-500/20', label: '危险' };
      default:
        return { color: 'text-gray-400', bg: 'bg-gray-500/20', label: '未知' };
    }
  };

  const statusConfig = getStatusConfig(risk.status);

  const formatValue = (value) => {
    return (value || 0).toFixed(2);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">风险状态</span>
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusConfig.bg} ${statusConfig.color}`}>
          {statusConfig.label}
        </span>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">今日盈亏</span>
          <span className={`text-sm font-medium ${(risk.dailyPnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {(risk.dailyPnl || 0) >= 0 ? '+' : ''}{formatValue(risk.dailyPnl)} USDT
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">总盈亏</span>
          <span className={`text-sm font-medium ${(risk.totalPnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {(risk.totalPnl || 0) >= 0 ? '+' : ''}{formatValue(risk.totalPnl)} USDT
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">当前回撤</span>
          <span className={`text-sm font-medium ${(risk.currentDrawdown || 0) > 5 ? 'text-red-400' : (risk.currentDrawdown || 0) > 2 ? 'text-yellow-400' : 'text-green-400'}`}>
            {formatValue(risk.currentDrawdown)}%
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">最大回撤</span>
          <span className="text-sm font-medium text-gray-400">
            {formatValue(risk.maxDrawdown)}%
          </span>
        </div>
      </div>

      <div className="pt-2">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">回撤水平</span>
          <span className="text-xs text-gray-400">{formatValue(risk.currentDrawdown)}% / 10%</span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ${
              risk.currentDrawdown > 5 ? 'bg-red-500' : 
              risk.currentDrawdown > 2 ? 'bg-yellow-500' : 'bg-green-500'
            }`}
            style={{ width: `${Math.min((risk.currentDrawdown || 0) * 10, 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}