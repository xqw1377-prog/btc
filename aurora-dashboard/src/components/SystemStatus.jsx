export default function SystemStatus({ state }) {
  const modeColors = {
    NORMAL: 'bg-green-500',
    CAUTIOUS: 'bg-yellow-500',
    RISK_OFF: 'bg-orange-500',
    EMERGENCY: 'bg-red-500',
    KILL: 'bg-red-600',
    FREEZE: 'bg-yellow-600'
  };

  const positionColors = {
    LONG: 'text-green-400',
    SHORT: 'text-red-400',
    FLAT: 'text-gray-400'
  };

  const modeLabel = {
    NORMAL: '正常运行',
    CAUTIOUS: '谨慎模式',
    RISK_OFF: '风险关闭',
    EMERGENCY: '紧急状态',
    KILL: '已终止',
    FREEZE: '冻结'
  };

  const positionLabel = {
    LONG: '多头',
    SHORT: '空头',
    FLAT: '空仓'
  };

  return (
    <div className={`p-6 rounded-xl ${modeColors[state.mode] || modeColors.NORMAL} text-white shadow-lg`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold opacity-80">系统状态</h2>
        <div className={`w-3 h-3 rounded-full bg-white ${state.mode === 'NORMAL' ? 'animate-pulse' : ''}`} />
      </div>

      <h1 className="text-3xl font-bold mb-4">{modeLabel[state.mode] || '正常运行'}</h1>

      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">引擎</span>
          <span className="font-medium">{state.engine === 'TREND' ? '趋势引擎' : '执行引擎'}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">持仓方向</span>
          <span className={`font-medium ${positionColors[state.position] || positionColors.FLAT}`}>
            {positionLabel[state.position] || '空仓'}
          </span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">杠杆倍数</span>
          <span className="font-medium">{state.leverage}x</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">仓位占用</span>
          <span className="font-medium">{state.exposure}%</span>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-white/20">
        <div className="flex gap-2">
          <span className={`px-2 py-1 rounded text-xs font-medium ${state.engines?.trend ? 'bg-green-400/30 text-green-200' : 'bg-red-400/30 text-red-200'}`}>
            趋势: {state.engines?.trend ? '开启' : '关闭'}
          </span>
          <span className={`px-2 py-1 rounded text-xs font-medium ${state.engines?.execution ? 'bg-green-400/30 text-green-200' : 'bg-red-400/30 text-red-200'}`}>
            执行: {state.engines?.execution ? '开启' : '关闭'}
          </span>
        </div>
      </div>

      <button
        onClick={() => {
          const newState = !state.killSwitch;
          console.log('Kill switch:', newState ? 'ACTIVE' : 'INACTIVE');
        }}
        className={`mt-4 w-full py-2 rounded-lg font-medium transition-all ${
          state.killSwitch
            ? 'bg-red-700 hover:bg-red-800'
            : 'bg-white/20 hover:bg-white/30'
        }`}
      >
        {state.killSwitch ? '🔴 紧急停止已激活' : '🛡️ 激活紧急停止'}
      </button>
    </div>
  );
}
