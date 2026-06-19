import { useEffect, useRef, useState } from 'react';

export default function KLineChart({ marketData }) {
  const chartContainerRef = useRef(null);
  const canvasRef = useRef(null);
  const [chartLoaded, setChartLoaded] = useState(false);

  useEffect(() => {
    if (!marketData?.klines || marketData.klines.length === 0) return;
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const klines = marketData.klines;

    const width = canvas.width;
    const height = canvas.height;
    const padding = { top: 20, right: 60, bottom: 30, left: 10 };

    ctx.clearRect(0, 0, width, height);

    const prices = klines.flatMap(k => [k.high, k.low]);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = maxPrice - minPrice || 1;

    const candleWidth = (width - padding.left - padding.right) / klines.length;
    const bodyWidth = candleWidth * 0.7;

    const scaleY = (price) => {
      return padding.top + (1 - (price - minPrice) / priceRange) * (height - padding.top - padding.bottom);
    };

    ctx.strokeStyle = '#2a2a3e';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (i / 4) * (height - padding.top - padding.bottom);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();

      const price = maxPrice - (i / 4) * priceRange;
      ctx.fillStyle = '#6b7280';
      ctx.font = '10px Inter, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`$${price.toLocaleString('en-US', { minimumFractionDigits: 0 })}`, width - padding.right + 5, y + 3);
    }

    klines.forEach((kline, i) => {
      const x = padding.left + i * candleWidth + candleWidth / 2;
      const isGreen = kline.close >= kline.open;
      const color = isGreen ? '#22c55e' : '#ef4444';

      const openY = scaleY(kline.open);
      const closeY = scaleY(kline.close);
      const highY = scaleY(kline.high);
      const lowY = scaleY(kline.low);

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, highY);
      ctx.lineTo(x, lowY);
      ctx.stroke();

      const bodyTop = Math.min(openY, closeY);
      const bodyHeight = Math.max(Math.abs(closeY - openY), 1);

      ctx.fillStyle = color;
      ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
    });

    const volumeHeight = height * 0.15;
    const maxVolume = Math.max(...klines.map(k => k.volume));

    klines.forEach((kline, i) => {
      const x = padding.left + i * candleWidth + candleWidth / 2;
      const isGreen = kline.close >= kline.open;
      const volHeight = (kline.volume / maxVolume) * volumeHeight;

      ctx.fillStyle = isGreen ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)';
      ctx.fillRect(x - bodyWidth / 2, height - padding.bottom - volHeight, bodyWidth, volHeight);
    });

    setChartLoaded(true);
  }, [marketData]);

  const klines = marketData?.klines || [];
  const lastKline = klines[klines.length - 1] || {};

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '14px', fontWeight: '500' }}>BTC/USDT</span>
          <span style={{ fontSize: '11px', color: '#6b7280' }}>永续合约</span>
          <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '4px', background: 'rgba(34, 197, 94, 0.2)', color: '#22c55e' }}>1分钟</span>
        </div>
        <div style={{ fontSize: '11px', color: '#6b7280' }}>{klines.length} 根K线</div>
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '12px' }}>
        <span style={{ fontSize: '28px', fontWeight: 'bold' }}>
          ${(marketData?.price || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </span>
        <span style={{ fontSize: '14px', color: (marketData?.priceChange || 0) >= 0 ? '#22c55e' : '#ef4444' }}>
          {(marketData?.priceChange || 0) >= 0 ? '+' : ''}{(marketData?.priceChange || 0).toFixed(2)} ({(marketData?.priceChangePercent || 0) >= 0 ? '+' : ''}{(marketData?.priceChangePercent || 0).toFixed(2)}%)
        </span>
      </div>

      <div style={{ position: 'relative', background: '#1a1a2e', borderRadius: '8px', overflow: 'hidden' }}>
        <canvas
          ref={canvasRef}
          width={800}
          height={300}
          style={{ width: '100%', height: '256px' }}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginTop: '12px' }}>
        <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
          <div style={{ fontSize: '11px', color: '#6b7280' }}>开盘价</div>
          <div style={{ fontSize: '13px', fontWeight: '500' }}>${(lastKline.open || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
        </div>
        <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
          <div style={{ fontSize: '11px', color: '#6b7280' }}>最高价</div>
          <div style={{ fontSize: '13px', fontWeight: '500' }}>${(lastKline.high || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
        </div>
        <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
          <div style={{ fontSize: '11px', color: '#6b7280' }}>最低价</div>
          <div style={{ fontSize: '13px', fontWeight: '500' }}>${(lastKline.low || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
        </div>
        <div style={{ background: '#1f2937', borderRadius: '8px', padding: '8px' }}>
          <div style={{ fontSize: '11px', color: '#6b7280' }}>成交量</div>
          <div style={{ fontSize: '13px', fontWeight: '500' }}>{(lastKline.volume || 0).toFixed(2)}</div>
        </div>
      </div>
    </div>
  );
}