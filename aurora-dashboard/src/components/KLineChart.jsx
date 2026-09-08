import { useEffect, useRef } from 'react';

export default function KLineChart({ marketData }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const klines = Array.isArray(marketData?.klines) ? marketData.klines : [];
  const observable = marketData?.meta?.status === 'ok';

  useEffect(() => {
    if (!observable || klines.length === 0 || !canvasRef.current || !containerRef.current) return undefined;

    const canvas = canvasRef.current;
    const container = containerRef.current;

    const draw = () => {
      const width = Math.max(container.clientWidth, 320);
      const height = Math.max(container.clientHeight, 280);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const ctx = canvas.getContext('2d');
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const padding = { top: 18, right: 72, bottom: 28, left: 8 };
      const chartHeight = height - padding.top - padding.bottom;
      const chartWidth = width - padding.left - padding.right;
      const prices = klines.flatMap((bar) => [Number(bar.high), Number(bar.low)]).filter(Number.isFinite);
      if (prices.length === 0) return;
      const minPrice = Math.min(...prices);
      const maxPrice = Math.max(...prices);
      const priceRange = maxPrice - minPrice || 1;
      const scaleY = (price) => padding.top + (1 - (price - minPrice) / priceRange) * chartHeight;

      ctx.lineWidth = 1;
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      for (let i = 0; i <= 4; i += 1) {
        const y = padding.top + (i / 4) * chartHeight;
        ctx.strokeStyle = '#202a35';
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(width - padding.right, y);
        ctx.stroke();
        const price = maxPrice - (i / 4) * priceRange;
        ctx.fillStyle = '#647386';
        ctx.fillText(`$${price.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, width - padding.right + 8, y + 3);
      }

      const candleWidth = chartWidth / klines.length;
      const bodyWidth = Math.max(2, candleWidth * 0.58);
      const maxVolume = Math.max(...klines.map((bar) => Number(bar.volume) || 0), 1);

      klines.forEach((bar, index) => {
        const open = Number(bar.open);
        const close = Number(bar.close);
        const high = Number(bar.high);
        const low = Number(bar.low);
        if (![open, close, high, low].every(Number.isFinite)) return;
        const x = padding.left + index * candleWidth + candleWidth / 2;
        const positive = close >= open;
        const color = positive ? '#38b887' : '#e05a5a';
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, scaleY(high));
        ctx.lineTo(x, scaleY(low));
        ctx.stroke();
        const bodyTop = Math.min(scaleY(open), scaleY(close));
        ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, Math.max(Math.abs(scaleY(close) - scaleY(open)), 1));

        const volumeHeight = ((Number(bar.volume) || 0) / maxVolume) * (chartHeight * 0.13);
        ctx.fillStyle = positive ? 'rgba(56,184,135,.22)' : 'rgba(224,90,90,.22)';
        ctx.fillRect(x - bodyWidth / 2, padding.top + chartHeight - volumeHeight, bodyWidth, volumeHeight);
      });
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(container);
    return () => observer.disconnect();
  }, [klines, observable]);

  const last = klines[klines.length - 1];
  return (
    <div className="kline-observation">
      <div className="chart-stats">
        <div><span>Bars observed</span><strong>{observable ? klines.length : 'UNKNOWN'}</strong></div>
        <div><span>Latest bar ID</span><strong>{observable && last?.time ? `BTCUSDT · 1m · ${last.time}` : 'UNKNOWN'}</strong></div>
        <div><span>Closed-bar evidence</span><strong className="unknown-value">NOT PROVIDED BY FEED</strong></div>
      </div>
      <div className="canvas-frame" ref={containerRef}>
        {observable && klines.length > 0 ? (
          <canvas ref={canvasRef} aria-label="BTCUSDT 1分钟交易所K线观察图" />
        ) : (
          <div className="chart-unavailable">
            <strong>MARKET DATA UNKNOWN</strong>
            <span>没有可验证的新鲜 K 线观察；不绘制零值图表。</span>
          </div>
        )}
      </div>
    </div>
  );
}
