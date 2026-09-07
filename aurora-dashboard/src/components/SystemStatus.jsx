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
    FLAT: 'text-gray-400',
    UNKNOWN: 'text-yellow-400',
    OPEN: 'text-green-400'
  };

  const modeLabel = {
    NORMAL: '正常运行',
    CAUTIOUS: '谨慎模式',
    RISK_OFF: '风险关闭',
    EMERGENCY: '紧急状态',
    KILL: '已终止',
    FREEZE: '冻结',
    UNKNOWN: '状态未确认'
  };

  const positionLabel = {
    LONG: '多头',
    SHORT: '空头',
    FLAT: '空仓',
    OPEN: '持仓',
    UNKNOWN: '未知（查询未成功）'
  };

  const dataStatus = state.meta?.status || 'unknown';
  const dataStatusLabel = {
    ok: '有效',
    stale: '陈旧（最近成功时间见上）',
    unknown: '未知（尚未成功采集）',
    error: '读取失败'
  };

  return (
    <div className={`p-6 rounded-xl ${modeColors[state.mode] || modeColors.NORMAL} text-white shadow-lg`}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold opacity-80">观察状态（只读）</h2>
        <div className={`w-3 h-3 rounded-full ${dataStatus === 'ok' ? 'bg-white animate-pulse' : 'bg-yellow-200'}`} />
      </div>

      <h1 className="text-3xl font-bold mb-4">{modeLabel[state.mode] || '状态未确认'}</h1>

      <div className="space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">引擎</span>
          <span className="font-medium">{state.engine === 'TREND' ? '趋势引擎' : '执行引擎'}</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">持仓方向</span>
          <span className={`font-medium ${positionColors[state.positionsState] || positionColors.UNKNOWN}`}>
            {positionLabel[state.positionsState] || '未知'}
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

      <div className="mt-4 pt-4 border-t border-white/20 space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">数据状态</span>
          <span className="font-medium">{dataStatusLabel[dataStatus] || dataStatus}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">保护单核验</span>
          <span className="font-medium">未核验</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm opacity-80">账本对账</span>
          <span className="font-medium">未由本观察面证明</span>
        </div>
      </div>

      <div className="mt-4 text-xs opacity-70">
        只读观察面板：不提供交易操作入口；连接状态不代表数据源已对账。
      </div>
    </div>
  );
}
