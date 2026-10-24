import { useEffect, useRef } from "react";
import { PAL } from "./palette";

function seedRand(seed) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

export const TF_PRESETS = Object.freeze({
  "3m": { count: 80, volScale: 0.07, barMinutes: 3, bodyScale: 0.55 },
  "1H": { count: 48, volScale: 0.28, barMinutes: 60, bodyScale: 0.62 },
  "4H": { count: 42, volScale: 0.5, barMinutes: 240, bodyScale: 0.62 },
  "1D": { count: 32, volScale: 1, barMinutes: 1440, bodyScale: 0.62 },
});

export const DEFAULT_TF = "3m";

/** Convert WS kline records (ms timestamps) into chart bar objects. */
export function normalizeKlines(records, timeframe = DEFAULT_TF) {
  if (!records?.length) return [];
  return records.map((r, i) => ({
    i,
    open: r.open,
    high: r.high,
    low: r.low,
    close: r.close,
    volume: r.volume ?? 0,
    time: r.time instanceof Date ? r.time : new Date(Number(r.time)),
    timeframe,
  }));
}

export function genCandles(seed, base = 118500, vol = 1200, timeframe = DEFAULT_TF) {
  const preset = TF_PRESETS[timeframe] || TF_PRESETS[DEFAULT_TF];
  const rand = seedRand(seed + timeframe.charCodeAt(0));
  let price = base;
  const effectiveVol = vol * preset.volScale;
  const anchor = new Date("2026-09-09T12:00:00Z");

  return Array.from({ length: preset.count }, (_, i) => {
    const open = price;
    const delta = (rand() - 0.46) * effectiveVol;
    const close = open + delta;
    const high = Math.max(open, close) + rand() * effectiveVol * 0.35;
    const low = Math.min(open, close) - rand() * effectiveVol * 0.35;
    price = close;
    const time = new Date(anchor.getTime() - (preset.count - 1 - i) * preset.barMinutes * 60_000);
    return { i, open, close, high, low, volume: 0.25 + rand() * 0.75, time, timeframe };
  });
}

export function formatAxisLabel(time, timeframe) {
  if (!time) return "";
  if (timeframe === "3m" || timeframe === "1H") {
    const h = String(time.getUTCHours()).padStart(2, "0");
    const m = String(time.getUTCMinutes()).padStart(2, "0");
    return `${h}:${m}`;
  }
  return `${time.getUTCMonth() + 1}/${time.getUTCDate()}`;
}

export function axisLabelsForBars(bars, timeframe, slots = 4) {
  if (!bars.length) return [];
  if (slots <= 1) return [formatAxisLabel(bars[bars.length - 1]?.time, timeframe)];
  const picks = Array.from({ length: slots }, (_, i) => {
    const idx = Math.round((i / (slots - 1)) * (bars.length - 1));
    return formatAxisLabel(bars[idx]?.time, timeframe);
  });
  return picks;
}

export function genLine(seed, count = 48, base = 0.042, trend = -0.00015) {
  const rand = seedRand(seed);
  let v = base;
  return Array.from({ length: count }, (_, i) => {
    v += trend + (rand() - 0.5) * 0.0008;
    return { i, v: Math.max(0.01, v) };
  });
}

export function genPerf(seed, count = 60) {
  const rand = seedRand(seed);
  let aurora = 1.0;
  let hodl = 1.0;
  return Array.from({ length: count }, (_, i) => {
    aurora += 0.0018 + rand() * 0.0035;
    hodl += 0.0009 + rand() * 0.0018;
    return { i, aurora, hodl };
  });
}

function useCanvasDraw(ref, containerRef, drawFn, deps) {
  useEffect(() => {
    const container = containerRef.current;
    const canvas = ref.current;
    if (!container || !canvas) return undefined;

    const draw = () => {
      const w = Math.max(container.clientWidth, 120);
      const h = Math.max(container.clientHeight, 80);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = w * ratio;
      canvas.height = h * ratio;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      drawFn(ctx, w, h);
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(container);
    return () => ro.disconnect();
  }, deps);
}

function formatPriceLabel(price) {
  if (price >= 1000) return `$${(price / 1000).toFixed(1)}k`;
  return `$${price.toFixed(0)}`;
}

export function ChartUnavailable({ label = "NOT CONNECTED", detail }) {
  return (
    <div className="chart-frame chart-unavailable" aria-label={label}>
      <span className="chart-unavail-label">{label}</span>
      {detail ? <span className="chart-unavail-detail">{detail}</span> : null}
    </div>
  );
}

export function CandlestickChart({ data, timeframe = DEFAULT_TF, fixture = true }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const preset = TF_PRESETS[timeframe] || TF_PRESETS[DEFAULT_TF];

  useCanvasDraw(
    canvasRef,
    containerRef,
    (ctx, w, h) => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = PAL.chartBg;
      ctx.fillRect(0, 0, w, h);

      const pad = { t: 12, r: 56, b: 22, l: 6 };
      const cw = w - pad.l - pad.r;
      const ch = h - pad.t - pad.b;
      const prices = data.flatMap((b) => [b.high, b.low]);
      const min = Math.min(...prices);
      const max = Math.max(...prices);
      const range = max - min || 1;
      const sy = (p) => pad.t + (1 - (p - min) / range) * ch;

      ctx.strokeStyle = PAL.grid;
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.t + (i / 4) * ch;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();
        const price = max - (i / 4) * range;
        ctx.fillStyle = PAL.textDim;
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = "left";
        ctx.fillText(formatPriceLabel(price), w - pad.r + 6, y + 3);
      }

      const barW = cw / data.length;
      const bodyW = Math.max(timeframe === "3m" ? 2 : 3, barW * preset.bodyScale);
      const maxVol = Math.max(...data.map((b) => b.volume), 0.01);
      const volH = ch * 0.14;

      data.forEach((bar, idx) => {
        const x = pad.l + idx * barW + barW / 2;
        const up = bar.close >= bar.open;
        const color = up ? PAL.candleUp : PAL.candleDown;
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, sy(bar.high));
        ctx.lineTo(x, sy(bar.low));
        ctx.stroke();
        const top = Math.min(sy(bar.open), sy(bar.close));
        const bodyH = Math.max(Math.abs(sy(bar.close) - sy(bar.open)), 1.5);
        ctx.fillRect(x - bodyW / 2, top, bodyW, bodyH);

        const vh = (bar.volume / maxVol) * volH;
        ctx.fillStyle = up ? "rgba(16,185,129,.22)" : "rgba(239,68,68,.14)";
        ctx.fillRect(x - bodyW / 2, pad.t + ch - vh, bodyW, vh);
      });

      ctx.fillStyle = PAL.textDim;
      ctx.font = '9px "IBM Plex Mono", monospace';
      const xLabels = axisLabelsForBars(data, timeframe);
      xLabels.forEach((lb, i) => {
        const x = pad.l + (i / (xLabels.length - 1)) * cw;
        ctx.textAlign = "center";
        ctx.fillText(lb, x, h - 6);
      });

      ctx.textAlign = "left";
      ctx.fillStyle = PAL.textSecondary;
      ctx.font = '700 9px "IBM Plex Mono", monospace';
      ctx.fillText(timeframe, pad.l + 4, pad.t + 10);
      if (fixture) {
        ctx.fillStyle = PAL.fixture;
        ctx.font = '600 8px "IBM Plex Mono", monospace';
        ctx.fillText("· FIXTURE", pad.l + 28, pad.t + 10);
      }
    },
    [data, timeframe, fixture, preset.bodyScale],
  );

  return (
    <div className="chart-frame chart-frame-candle" ref={containerRef}>
      <canvas ref={canvasRef} aria-label={`${timeframe} K 线${fixture ? " · 夹具" : ""}`} />
    </div>
  );
}

export function LineChart({ data, field = "v", color = PAL.lineEthBtc, muted = false }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  useCanvasDraw(
    canvasRef,
    containerRef,
    (ctx, w, h) => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = PAL.chartBg;
      ctx.fillRect(0, 0, w, h);

      const pad = { t: 14, r: 10, b: 20, l: 10 };
      const cw = w - pad.l - pad.r;
      const ch = h - pad.t - pad.b;
      const vals = data.map((d) => d[field]);
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      const range = max - min || 0.001;
      const sx = (i) => pad.l + (i / (data.length - 1)) * cw;
      const sy = (v) => pad.t + (1 - (v - min) / range) * ch;

      ctx.strokeStyle = PAL.grid;
      ctx.lineWidth = 1;
      for (let i = 0; i <= 3; i++) {
        const y = pad.t + (i / 3) * ch;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();
      }

      const strokeColor = muted ? PAL.textDim : color;
      ctx.beginPath();
      data.forEach((d, i) => {
        const x = sx(i);
        const y = sy(d[field]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.lineTo(sx(data.length - 1), pad.t + ch);
      ctx.lineTo(sx(0), pad.t + ch);
      ctx.closePath();
      ctx.fillStyle = muted ? "rgba(148,163,184,.1)" : PAL.lineEthBtcFill;
      ctx.fill();

      ctx.beginPath();
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2;
      data.forEach((d, i) => {
        const x = sx(i);
        const y = sy(d[field]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      ctx.fillStyle = PAL.textDim;
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = "left";
      ["Jan", "May", "Sep"].forEach((lb, i) => {
        ctx.fillText(lb, pad.l + (i / 2) * cw - 4, h - 5);
      });
    },
    [data, field, color, muted],
  );

  return (
    <div className="chart-frame chart-frame-line" ref={containerRef}>
      <canvas ref={canvasRef} aria-hidden="true" />
    </div>
  );
}

export function PerfChart({ data, fixture = true }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  useCanvasDraw(
    canvasRef,
    containerRef,
    (ctx, w, h) => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = PAL.chartBg;
      ctx.fillRect(0, 0, w, h);

      const pad = { t: 18, r: 10, b: 12, l: 10 };
      const cw = w - pad.l - pad.r;
      const ch = h - pad.t - pad.b;
      const all = data.flatMap((d) => [d.aurora, d.hodl]);
      const min = Math.min(...all) * 0.998;
      const max = Math.max(...all) * 1.002;
      const range = max - min || 0.01;
      const sx = (i) => pad.l + (i / (data.length - 1)) * cw;
      const sy = (v) => pad.t + (1 - (v - min) / range) * ch;

      ctx.strokeStyle = PAL.grid;
      for (let i = 0; i <= 2; i++) {
        const y = pad.t + (i / 2) * ch;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();
      }

      const drawLine = (field, lineColor, dash, fill) => {
        ctx.beginPath();
        data.forEach((d, i) => {
          const x = sx(i);
          const y = sy(d[field]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        if (fill) {
          ctx.lineTo(sx(data.length - 1), pad.t + ch);
          ctx.lineTo(sx(0), pad.t + ch);
          ctx.closePath();
          ctx.fillStyle = fill;
          ctx.fill();
          ctx.beginPath();
          data.forEach((d, i) => {
            const x = sx(i);
            const y = sy(d[field]);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
        }
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = field === "aurora" ? 2.5 : 1.5;
        ctx.setLineDash(dash);
        ctx.stroke();
        ctx.setLineDash([]);
      };

      drawLine("aurora", fixture ? PAL.perfAurora : PAL.green, [], PAL.perfAuroraFill);
      drawLine("hodl", PAL.perfHodl, [5, 4], null);

      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.fillStyle = PAL.perfHodl;
      ctx.fillText("— HODL", pad.l + 4, pad.t + 2);
      ctx.fillStyle = fixture ? PAL.btc : PAL.green;
      ctx.fillText("— AURORA", pad.l + 58, pad.t + 2);
    },
    [data, fixture],
  );

  return (
    <div className="chart-frame chart-frame-perf" ref={containerRef}>
      <canvas ref={canvasRef} aria-hidden="true" />
    </div>
  );
}

export function DonutChart({ segments, muted = false }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let acc = 0;
  const stops = segments.map((seg) => {
    const start = (acc / total) * 360;
    acc += seg.value;
    const end = (acc / total) * 360;
    const color = muted ? PAL.candleMutedDown : seg.color;
    return `${color} ${start}deg ${end}deg`;
  });

  return (
    <div
      className={`donut-chart ${muted ? "is-muted" : ""}`}
      style={{ background: stops.length ? `conic-gradient(${stops.join(", ")})` : PAL.grid }}
      aria-hidden="true"
    >
      <div className="donut-hole" />
    </div>
  );
}
