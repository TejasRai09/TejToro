import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
} from 'lightweight-charts';

export default function CandleChart({ instrumentKey, sig, ltp }) {
  const containerRef  = useRef(null);
  const chartRef      = useRef(null);
  const candleRef     = useRef(null);
  const vwapRef       = useRef(null);
  const candleDataRef = useRef([]);

  // ── Create chart + OHLC tooltip ───────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    containerRef.current.style.position = 'relative';

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#9ca3af',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: 'rgba(0,0,0,0.04)' },
        horzLines: { color: 'rgba(0,0,0,0.04)' },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.12, bottom: 0.08 },
        textColor: '#9ca3af',
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(0,0,0,0.12)',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#1f2937',
        },
        horzLine: {
          color: 'rgba(0,0,0,0.12)',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#1f2937',
        },
      },
      height: 260,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor:         '#059669',
      downColor:       '#dc2626',
      borderUpColor:   '#059669',
      borderDownColor: '#dc2626',
      wickUpColor:     '#059669',
      wickDownColor:   '#dc2626',
      wickVisible:     true,
    });

    const vwapSeries = chart.addLineSeries({
      color:                  '#7c3aed',
      lineWidth:              2,
      priceLineVisible:       false,
      lastValueVisible:       true,
      crosshairMarkerVisible: true,
    });

    chartRef.current  = chart;
    candleRef.current = candleSeries;
    vwapRef.current   = vwapSeries;

    // ── Price lines for trade levels ────────────────────────────────────────
    if (sig) {
      candleSeries.createPriceLine({
        price: sig.entry, color: '#059669', lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true,
        title: `Entry ₹${sig.entry}`,
      });
      candleSeries.createPriceLine({
        price: sig.sl, color: '#dc2626', lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true,
        title: `SL ₹${sig.sl}`,
      });
      candleSeries.createPriceLine({
        price: sig.target, color: '#b45309', lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true,
        title: `Target ₹${sig.target}`,
      });
    }

    // ── OHLC Tooltip ─────────────────────────────────────────────────────────
    const tooltip = document.createElement('div');
    tooltip.style.cssText = `
      display: none;
      position: absolute;
      top: 8px;
      pointer-events: none;
      z-index: 10;
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 7px 11px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.10);
      white-space: nowrap;
      min-width: 148px;
    `;
    containerRef.current.appendChild(tooltip);

    const onCrosshair = (param) => {
      if (
        !param.point ||
        !param.time  ||
        param.point.x < 0 ||
        param.point.y < 0
      ) {
        tooltip.style.display = 'none';
        return;
      }

      const bar = param.seriesData.get(candleSeries);
      if (!bar) { tooltip.style.display = 'none'; return; }

      const isUp = bar.close >= bar.open;
      const col  = isUp ? '#059669' : '#dc2626';

      // param.time is the IST-shifted UTC timestamp — read as UTC to get IST display
      const d  = new Date(param.time * 1000);
      const hh = String(d.getUTCHours()).padStart(2, '0');
      const mm = String(d.getUTCMinutes()).padStart(2, '0');

      const w    = containerRef.current?.clientWidth ?? 400;
      const left = param.point.x > w / 2
        ? param.point.x - 162
        : param.point.x + 14;

      tooltip.style.left    = `${left}px`;
      tooltip.style.display = 'block';
      tooltip.style.borderLeft = `3px solid ${col}`;

      tooltip.innerHTML = `
        <div style="color:#9ca3af;font-size:10px;margin-bottom:5px;letter-spacing:0.04em;">
          ${hh}:${mm}
        </div>
        <div style="display:grid;grid-template-columns:12px 1fr;row-gap:3px;column-gap:10px;align-items:center;">
          <span style="color:#9ca3af;font-size:10px;">O</span>
          <span style="color:${col};">₹${bar.open.toFixed(2)}</span>
          <span style="color:#9ca3af;font-size:10px;">H</span>
          <span style="color:#059669;">₹${bar.high.toFixed(2)}</span>
          <span style="color:#9ca3af;font-size:10px;">L</span>
          <span style="color:#dc2626;">₹${bar.low.toFixed(2)}</span>
          <span style="color:#9ca3af;font-size:10px;">C</span>
          <span style="color:${col};font-weight:700;">₹${bar.close.toFixed(2)}</span>
        </div>
      `;
    };

    chart.subscribeCrosshairMove(onCrosshair);

    // ── Resize observer ─────────────────────────────────────────────────────
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        chart.applyOptions({ width: e.contentRect.width });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      chart.unsubscribeCrosshairMove(onCrosshair);
      if (tooltip.parentNode) tooltip.parentNode.removeChild(tooltip);
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      candleRef.current = null;
      vwapRef.current   = null;
    };
  }, [instrumentKey, sig?.entry, sig?.sl, sig?.target]);

  // ── Fetch candle data — refresh every 10 min to pick up new completed candles
  useEffect(() => {
    if (!candleRef.current || !vwapRef.current || !instrumentKey) return;

    const fetchCandles = () =>
      fetch(`/api/chart/${encodeURIComponent(instrumentKey)}`)
        .then(r => r.json())
        .then(data => {
          if (!candleRef.current) return;
          const candles = data.candles || [];
          if (!candles.length) return;
          candleRef.current.setData(candles);
          candleDataRef.current = candles;
          if (data.vwap?.length) vwapRef.current.setData(data.vwap);
          chartRef.current?.timeScale().fitContent();
        })
        .catch(() => {});

    fetchCandles();
    const id = setInterval(fetchCandles, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [instrumentKey]);

  // ── Live LTP — update forming candle ─────────────────────────────────────
  useEffect(() => {
    if (!candleRef.current || ltp === null || ltp === undefined) return;
    const candles = candleDataRef.current;
    if (!candles.length) return;

    const last     = candles[candles.length - 1];
    const IST_OFF  = 5 * 3600 + 30 * 60;
    const nowUtcTs = Math.floor(Date.now() / 1000) + IST_OFF; // adjusted same as server
    if (nowUtcTs >= last.time + 10 * 60) return;

    candleRef.current.update({
      time:  last.time,
      open:  last.open,
      high:  Math.max(last.high, ltp),
      low:   Math.min(last.low,  ltp),
      close: ltp,
    });
  }, [ltp]);

  return <div ref={containerRef} style={{ width: '100%', height: '260px' }} />;
}
