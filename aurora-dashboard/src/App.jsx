import useWS from './hooks/useWS';
import SystemStatus from './components/SystemStatus';
import MarketPanel from './components/MarketPanel';
import RiskPanel from './components/RiskPanel';
import TradeScore from './components/TradeScore';
import PnLChart from './components/PnLChart';
import TradeList from './components/TradeList';
import KLineChart from './components/KLineChart';

function App() {
  const { system, market, risk, score, pnlData, trades } = useWS();

  const generateMockPnlData = () => {
    const data = [];
    const now = new Date();
    let pnl = 0;
    
    for (let i = 48; i >= 0; i--) {
      const time = new Date(now - i * 30 * 60 * 1000);
      pnl += (Math.random() - 0.45) * 100;
      data.push({
        time: time.toISOString(),
        pnl: Math.round(pnl * 100) / 100
      });
    }
    
    return data;
  };

  const mockTrades = [
    {
      id: '1',
      timestamp: new Date().toISOString(),
      engine: 'TREND',
      side: 'BUY',
      entryPrice: 67254.8,
      exitPrice: 67450.2,
      quantity: 0.2,
      pnl: 0.29,
      reason: 'BREAKOUT',
      regime: 'TREND',
      confidence: 0.82
    },
    {
      id: '2',
      timestamp: new Date(Date.now() - 300000).toISOString(),
      engine: 'EXECUTION',
      side: 'SELL',
      entryPrice: 67100.5,
      exitPrice: 66950.8,
      quantity: 0.1,
      pnl: 0.22,
      reason: 'VWAP REVERSION',
      regime: 'TREND',
      confidence: 0.75
    },
    {
      id: '3',
      timestamp: new Date(Date.now() - 600000).toISOString(),
      engine: 'TREND',
      side: 'BUY',
      entryPrice: 66890.1,
      exitPrice: null,
      quantity: 0.15,
      pnl: 0,
      reason: 'PULLBACK',
      regime: 'TREND',
      confidence: 0.78
    }
  ];

  const pnlDataToUse = pnlData.length > 0 ? pnlData : generateMockPnlData();
  const tradesToUse = trades.length > 0 ? trades : mockTrades;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-green-500 to-blue-500 flex items-center justify-center">
                <span className="text-xl font-bold">A</span>
              </div>
              <div>
                <h1 className="text-xl font-bold">AURORA</h1>
                <p className="text-xs text-gray-400">交易操作系统</p>
              </div>
            </div>
            <span className="text-xs text-gray-500">|</span>
            <span className="text-sm text-gray-400">仅BTC</span>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-right">
              <div className="text-xs text-gray-500">BTC/USDT 永续合约</div>
              <div className="text-2xl font-bold">
                ${market.price.toLocaleString('en-US', { minimumFractionDigits: 2 }) || '67,254.80'}
              </div>
              <div className="text-xs text-green-400">+1.22%</div>
            </div>

            <div className="text-right">
              <div className="text-xs text-gray-500">系统模式</div>
              <div className="text-lg font-bold text-green-400">自动模式</div>
            </div>

            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-sm text-gray-400">已连接</span>
            </div>
          </div>
        </div>
      </header>

      <main className="p-6">
        <div className="grid grid-cols-12 gap-6">
          <div className="col-span-3">
            <SystemStatus state={system} />
          </div>

          <div className="col-span-6">
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
              <KLineChart marketData={market} />
            </div>
          </div>

          <div className="col-span-3">
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold mb-4 text-gray-300">持仓信息</h2>
              
              <div className="flex items-center gap-2 mb-4">
                <span className="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">
                  多头
                </span>
                <span className="text-lg font-bold">0.518 BTC</span>
              </div>

              <div className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-400">开仓均价</span>
                  <span className="text-white">$66,845.12</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">当前价格</span>
                  <span className="text-white">$67,254.80</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">浮动盈亏</span>
                  <span className="text-green-400">+214.36 USDT</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">保证金</span>
                  <span className="text-white">$16,580.21</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">杠杆倍数</span>
                  <span className="text-white">2.1x</span>
                </div>
              </div>

              <div className="mt-4">
                <div className="flex justify-between text-xs text-gray-400 mb-2">
                  <span>仓位占用</span>
                  <span>42.3%</span>
                </div>
                <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div className="h-full bg-green-500 w-[42.3%]" />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 mt-4">
                <button className="py-2 px-3 rounded-lg bg-green-500/20 text-green-400 text-xs hover:bg-green-500/30">
                  反手开空
                </button>
                <button className="py-2 px-3 rounded-lg bg-gray-800 text-gray-400 text-xs hover:bg-gray-700">
                  部分平仓
                </button>
                <button className="py-2 px-3 rounded-lg bg-red-500/20 text-red-400 text-xs hover:bg-red-500/30">
                  全部平仓
                </button>
              </div>
            </div>
          </div>

          <div className="col-span-4">
            <MarketPanel market={market} />
          </div>

          <div className="col-span-4">
            <TradeScore score={score} />
          </div>

          <div className="col-span-4">
            <RiskPanel risk={risk} />
          </div>

          <div className="col-span-8">
            <PnLChart data={pnlDataToUse} />
          </div>

          <div className="col-span-4">
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold mb-4 text-gray-300">引擎状态</h2>
              
              <div className="space-y-4">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-gray-400">趋势引擎</span>
                    <span className="px-2 py-0.5 rounded text-xs bg-green-500/20 text-green-400">开启</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">置信度</span>
                    <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-blue-500 w-[82%]" />
                    </div>
                    <span className="text-xs text-gray-400">0.82</span>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-gray-400">执行引擎</span>
                    <span className="px-2 py-0.5 rounded text-xs bg-green-500/20 text-green-400">开启</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">置信度</span>
                    <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-500 w-[68%]" />
                    </div>
                    <span className="text-xs text-gray-400">0.68</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="col-span-12">
            <TradeList trades={tradesToUse} />
          </div>
        </div>
      </main>

      <footer className="bg-gray-900 border-t border-gray-800 px-6 py-3 mt-6">
        <div className="flex items-center justify-between text-xs text-gray-500">
          <div className="flex items-center gap-6">
            <span>API延迟: 48ms</span>
            <span>WS延迟: 32ms</span>
            <span>状态: 正常</span>
          </div>
          <span>版权 2024 AURORA 交易操作系统 | 仅BTC | 版本 1.0.0</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
