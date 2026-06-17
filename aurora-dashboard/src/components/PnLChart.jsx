import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

export default function PnLChart({ data }) {
  const formatX = (tick) => {
    if (typeof tick === 'string') {
      return tick.split(' ')[1]?.substring(0, 5) || '';
    }
    return '';
  };

  const formatY = (value) => {
    if (value >= 0) return `+$${value.toFixed(2)}`;
    return `-$${Math.abs(value).toFixed(2)}`;
  };

  return (
    <div className="p-6 bg-gray-900 rounded-xl border border-gray-800">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-300">盈亏概览</h2>
        <div className="flex gap-4">
          {['1日', '1周', '1月', '全部'].map((period, index) => (
            <button
              key={period}
              className={`text-xs px-2 py-1 rounded ${index === 2 ? 'bg-green-500 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
            >
              {period}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-baseline gap-2 mb-4">
        <span className="text-3xl font-bold text-green-400">
          +$3,456.78
        </span>
        <span className="text-sm text-gray-400">
          +712%
        </span>
      </div>

      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
            <XAxis 
              dataKey="time" 
              tickFormatter={formatX}
              tickLine={{ stroke: '#3a3a5e' }}
              axisLine={{ stroke: '#3a3a5e' }}
              tick={{ fill: '#6a6a8e', fontSize: 10 }}
            />
            <YAxis 
              tickFormatter={formatY}
              tickLine={{ stroke: '#3a3a5e' }}
              axisLine={{ stroke: '#3a3a5e' }}
              tick={{ fill: '#6a6a8e', fontSize: 10 }}
            />
            <Tooltip 
              formatter={(value) => [`$${value.toFixed(2)}`, '盈亏']}
              contentStyle={{ 
                backgroundColor: '#1a1a2e', 
                borderColor: '#3a3a5e',
                borderRadius: '8px',
                fontSize: '12px'
              }}
            />
            <Line 
              type="monotone" 
              dataKey="pnl" 
              stroke="#22c55e" 
              strokeWidth={2}
              dot={false}
              strokeLinecap="round"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-3 gap-4 mt-4">
        <div className="text-center">
          <div className="text-xs text-gray-400">胜率</div>
          <div className="text-lg font-semibold text-green-400">56.8%</div>
        </div>
        <div className="text-center">
          <div className="text-xs text-gray-400">盈利因子</div>
          <div className="text-lg font-semibold text-green-400">1.62</div>
        </div>
        <div className="text-center">
          <div className="text-xs text-gray-400">交易次数</div>
          <div className="text-lg font-semibold text-white">142</div>
        </div>
      </div>
    </div>
  );
}
