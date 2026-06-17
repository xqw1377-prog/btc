import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart } from 'lightweight-charts';

export default function KLineChart({ marketData }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candlestickSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [currentPrice, setCurrentPrice] = useState(67254.8);
  const [priceChange, setPriceChange] = useState(812.3);
  const [priceChangePercent, setPriceChangePercent] = useState(1.22);

  const generateMockData = useCallback(() => {
    const data = [];
    let basePrice = 66000;
    
    for (let i = 100; i >= 0; i--) {
      const time = Math.floor(Date.now() / 1000) - i * 3600;
      const volatility = (Math.random() - 0.5) * 800;
      const open = basePrice;
      const close = open + volatility;
      const high = Math.max(open, close) + Math.random() * 200;
      const low = Math.min(open, close) - Math.random() * 200;
      const volume = Math.random() * 50 + 10;
      
      data.push({
        time,
        open: parseFloat(open.toFixed(2)),
        high: parseFloat(high.toFixed(2)),
        low: parseFloat(low.toFixed(2)),
        close: parseFloat(close.toFixed(2)),
        volume: parseFloat(volume.toFixed(2))
      });
      
      basePrice = close;
    }
    
    return data;
  }, []);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#1a1a2e' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#2a2a3e' },
        horzLines: { color: '#2a2a3e' },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: '#3a3a5e',
      },
      timeScale: {
        borderColor: '#3a3a5e',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    const volumeSeries = chart.addHistogramSeries({
      color: '#4a5568',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    const mockData = generateMockData();
    const candleData = mockData.map(d => ({
      time: d.time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    const volumeData = mockData.map(d => ({
      time: d.time,
      value: d.volume,
      color: d.close >= d.open ? '#22c55e80' : '#ef444480',
    }));

    candlestickSeries.setData(candleData);
    volumeSeries.setData(volumeData);

    chart.timeScale().fitContent();

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;
    volumeSeriesRef.current = volumeSeries;

    setIsLoading(false);

    let updateInterval;
    
    if (marketData && marketData.price > 0) {
      updateInterval = setInterval(() => {
        const lastCandle = candleData[candleData.length - 1];
        const newClose = marketData.price || lastCandle.close + (Math.random() - 0.5) * 50;
        const newHigh = Math.max(lastCandle.high, newClose + Math.random() * 20);
        const newLow = Math.min(lastCandle.low, newClose - Math.random() * 20);

        const updatedCandle = {
          time: lastCandle.time,
          open: lastCandle.open,
          high: parseFloat(newHigh.toFixed(2)),
          low: parseFloat(newLow.toFixed(2)),
          close: parseFloat(newClose.toFixed(2)),
        };

        candleData.pop();
        candleData.push(updatedCandle);
        candlestickSeries.setData(candleData);

        setCurrentPrice(parseFloat(newClose.toFixed(2)));
        setPriceChange(marketData.priceChange || parseFloat(((newClose - mockData[0].open)).toFixed(2)));
        setPriceChangePercent(marketData.priceChangePercent || parseFloat((((newClose - mockData[0].open) / mockData[0].open) * 100).toFixed(2));
      }, 1000);
    } else {
      updateInterval = setInterval(() => {
        const lastCandle = candleData[candleData.length - 1];
        const newClose = lastCandle.close + (Math.random() - 0.5) * 50;
        const newHigh = Math.max(lastCandle.high, newClose + Math.random() * 20);
        const newLow = Math.min(lastCandle.low, newClose - Math.random() * 20);

        const updatedCandle = {
          time: lastCandle.time,
          open: lastCandle.open,
          high: parseFloat(newHigh.toFixed(2)),
          low: parseFloat(newLow.toFixed(2)),
          close: parseFloat(newClose.toFixed(2)),
        };

        candleData.pop();
        candleData.push(updatedCandle);
        candlestickSeries.setData(candleData);

        setCurrentPrice(parseFloat(newClose.toFixed(2)));
        const change = newClose - mockData[0].open;
        setPriceChange(parseFloat(change.toFixed(2)));
        setPriceChangePercent(parseFloat(((change / mockData[0].open) * 100).toFixed(2)));
      }, 1000);
    }

    return () => {
      clearInterval(updateInterval);
      if (chartRef.current) {
        chartRef.current.remove();
      }
    };
  }, [generateMockData, marketData]);

  useEffect(() => {
    if (marketData && marketData.price > 0) {
      setCurrentPrice(marketData.price);
      setPriceChange(marketData.priceChange || 0);
      setPriceChangePercent(marketData.priceChangePercent || 0);
    }
  }, [marketData]);

  if (isLoading) {
    return (
      <div className="h-64 bg-gray-800 rounded-lg flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-500 mx-auto mb-2" />
          <div className="text-sm text-gray-500">加载 K 线数据...</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">BTC/USDT 永续合约</span>
          {['1分', '5分', '15分', '1小时', '4小时', '1日'].map((period, index) => (
            <button
              key={period}
              className={`text-xs px-3 py-1 rounded ${index === 4 ? 'bg-green-500 text-white' : 'text-gray-400 hover:text-white'}`}
            >
              {period}
            </button>
          ))}
        </div>
        <div className="text-xs text-gray-500">Binance</div>
      </div>

      <div className="flex items-baseline gap-4 mb-4">
        <div className="text-3xl font-bold text-white">
          ${currentPrice.toLocaleString()}
        </div>
        <div className={`text-lg font-semibold ${priceChange >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {priceChange >= 0 ? '+' : ''}{priceChange.toLocaleString()} ({priceChangePercent >= 0 ? '+' : ''}{priceChangePercent}%)
        </div>
      </div>

      <div ref={chartContainerRef} className="h-64 bg-gray-800 rounded-lg" />

      <div className="grid grid-cols-4 gap-4 mt-4">
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs text-gray-400">开盘价</div>
          <div className="text-sm font-semibold">${66890.1.toLocaleString()}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs text-gray-400">最高价</div>
          <div className="text-sm font-semibold">${67655.2.toLocaleString()}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs text-gray-400">最低价</div>
          <div className="text-sm font-semibold">${66755.2.toLocaleString()}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs text-gray-400">成交量</div>
          <div className="text-sm font-semibold">12.45K</div>
        </div>
      </div>
    </div>
  );
}
