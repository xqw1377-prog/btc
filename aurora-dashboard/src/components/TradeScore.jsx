export default function TradeScore({ score }) {
  const getScoreColor = (score) => {
    if (score >= 70) return 'text-green-400';
    if (score >= 50) return 'text-yellow-400';
    if (score >= 30) return 'text-orange-400';
    return 'text-red-400';
  };

  const getScoreBg = (score) => {
    if (score >= 70) return 'bg-green-500';
    if (score >= 50) return 'bg-yellow-500';
    if (score >= 30) return 'bg-orange-500';
    return 'bg-red-500';
  };

  const getScoreLabel = (score) => {
    if (score >= 70) return '适合交易';
    if (score >= 50) return '谨慎交易';
    if (score >= 30) return '风险较高';
    return '避免交易';
  };

  const getScoreIcon = (score) => {
    if (score >= 70) return '📈';
    if (score >= 50) return '📊';
    if (score >= 30) return '⚠️';
    return '🔴';
  };

  return (
    <div className="space-y-3">
      <div className="text-center">
        <div className="text-3xl font-bold mb-1">
          <span className={getScoreColor(score)}>{score}</span>
          <span className="text-gray-500 text-lg"> / 100</span>
        </div>
        <div className={`text-sm font-medium ${getScoreColor(score)}`}>
          {getScoreIcon(score)} {getScoreLabel(score)}
        </div>
      </div>

      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div 
          className={`h-full transition-all duration-500 ${getScoreBg(score)}`}
          style={{ width: `${score}%` }}
        />
      </div>

      <div className="text-center">
        <span className="text-xs text-gray-500">系统置信度</span>
        <span className="text-xs text-gray-400 ml-2">{score}%</span>
      </div>
    </div>
  );
}