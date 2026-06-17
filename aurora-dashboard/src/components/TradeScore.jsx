export default function TradeScore({ score }) {
  const getScoreColor = () => {
    if (score >= 70) return 'text-green-400';
    if (score >= 40) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getScoreBgColor = () => {
    if (score >= 70) return 'from-green-500/20 to-green-600/10';
    if (score >= 40) return 'from-yellow-500/20 to-yellow-600/10';
    return 'from-red-500/20 to-red-600/10';
  };

  const getScoreGlowColor = () => {
    if (score >= 70) return 'shadow-green-500/50';
    if (score >= 40) return 'shadow-yellow-500/50';
    return 'shadow-red-500/50';
  };

  const getScoreMessage = () => {
    if (score >= 85) return '极佳 - 强烈买入信号';
    if (score >= 70) return '良好 - 确认交易';
    if (score >= 50) return '中性 - 谨慎操作';
    if (score >= 30) return '警告 - 减少仓位';
    return '危险 - 避免交易';
  };

  return (
    <div className={`p-6 rounded-xl bg-gradient-to-br ${getScoreBgColor()} border border-gray-800 shadow-lg ${getScoreGlowColor()}`}>
      <div className="text-center">
        <h2 className="text-lg font-semibold text-gray-300 mb-4">交易评分</h2>
        
        <div className="relative w-32 h-32 mx-auto mb-4">
          <svg className="w-full h-full transform -rotate-90">
            <circle
              cx="64"
              cy="64"
              r="56"
              stroke="#1a1a2e"
              strokeWidth="12"
              fill="none"
            />
            <circle
              cx="64"
              cy="64"
              r="56"
              stroke={score >= 70 ? '#22c55e' : score >= 40 ? '#eab308' : '#ef4444'}
              strokeWidth="12"
              fill="none"
              strokeLinecap="round"
              strokeDasharray={`${score * 3.52} 352`}
              className="transition-all duration-1000"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`text-4xl font-bold ${getScoreColor()}`}>
              {score}
            </span>
            <span className="text-xs text-gray-400">/ 100</span>
          </div>
        </div>

        <p className={`text-sm font-medium ${getScoreColor()}`}>
          {getScoreMessage()}
        </p>

        <div className="mt-4 pt-4 border-t border-gray-700">
          <div className="flex justify-between text-xs text-gray-400">
            <span>系统置信度</span>
            <span className={getScoreColor()}>{score}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}
