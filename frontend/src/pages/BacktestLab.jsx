import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  createChart, ColorType, CrosshairMode, LineStyle,
} from 'lightweight-charts';

const PAT_COLORS = {
  B:        '#2563eb',
  ENG:      '#059669',
  HAM:      '#b45309',
  MAR:      '#7c3aed',
  HAM2S:    '#db2777',
  FLAG:     '#f59e0b',
  TRI:      '#06b6d4',
  DTRI:     '#f97316',
  VCNB:     '#10b981',
  OPEN_RCL: '#e879f9',
};

const ALL_PATTERNS = ['B', 'ENG', 'HAM', 'MAR', 'HAM2S', 'FLAG', 'TRI', 'DTRI', 'VCNB', 'OPEN_RCL'];

// ── Small display helpers ──────────────────────────────────────────────────────

function PatBadge({ name }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: '4px',
      fontSize: '0.72rem', fontWeight: 700,
      background: (PAT_COLORS[name] || '#6b7280') + '18',
      color: PAT_COLORS[name] || '#6b7280', fontFamily: 'var(--mono)',
    }}>{name}</span>
  );
}

function OutcomeBadge({ outcome }) {
  const m = {
    WIN:  { color: '#059669', bg: 'rgba(5,150,105,0.10)',   label: 'WIN'  },
    SL:   { color: '#dc2626', bg: 'rgba(220,38,38,0.10)',   label: 'SL'   },
    OPEN: { color: '#6b7280', bg: 'rgba(107,114,128,0.10)', label: 'OPEN' },
  };
  const s = m[outcome] || m.OPEN;
  return (
    <span style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: '4px',
      fontSize: '0.72rem', fontWeight: 700,
      background: s.bg, color: s.color, fontFamily: 'var(--mono)',
    }}>{s.label}</span>
  );
}

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)', padding: '0.75rem 1.1rem', minWidth: 90,
    }}>
      <div style={{ fontSize: '1.15rem', fontWeight: 700, color: color || 'var(--text)', fontFamily: 'var(--mono)' }}>
        {value}
      </div>
      <div style={{ fontSize: '0.7rem', color: 'var(--muted)', marginTop: '2px' }}>{label}</div>
      {sub && <div style={{ fontSize: '0.66rem', color: 'var(--dim)', marginTop: '1px' }}>{sub}</div>}
    </div>
  );
}


// ── BtChart ────────────────────────────────────────────────────────────────────

function BtChart({ symbol, markers, focusDate, height = 420 }) {
  const mainH = Math.round(height * 0.72);
  const rsiH  = height - mainH - 4;

  const containerRef    = useRef(null);
  const rsiContainerRef = useRef(null);
  const chartRef        = useRef(null);
  const rsiChartRef     = useRef(null);
  const candleRef       = useRef(null);
  const vwapRef         = useRef(null);
  const rsiSeriesRef    = useRef(null);
  const focusDateRef    = useRef(focusDate);
  const syncingRef      = useRef(false);

  useEffect(() => { focusDateRef.current = focusDate; }, [focusDate]);

  // Create both charts once on mount
  useEffect(() => {
    if (!containerRef.current || !rsiContainerRef.current) return;
    containerRef.current.style.position = 'relative';

    // ── Main candle chart ──────────────────────────────────────────────
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#9ca3af', fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
      },
      grid: { vertLines: { color: 'rgba(0,0,0,0.04)' }, horzLines: { color: 'rgba(0,0,0,0.04)' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 5 },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(0,0,0,0.12)', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#1f2937' },
        horzLine: { color: 'rgba(0,0,0,0.12)', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#1f2937' },
      },
      height: mainH,
    });

    const candles = chart.addCandlestickSeries({
      upColor: '#059669', downColor: '#dc2626',
      borderUpColor: '#059669', borderDownColor: '#dc2626',
      wickUpColor: '#059669', wickDownColor: '#dc2626',
    });
    const vwap = chart.addLineSeries({
      color: '#7c3aed', lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    chartRef.current  = chart;
    candleRef.current = candles;
    vwapRef.current   = vwap;

    // OHLC tooltip
    const tip = document.createElement('div');
    tip.style.cssText = `display:none;position:absolute;top:8px;pointer-events:none;z-index:10;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:7px 11px;font-family:'JetBrains Mono',monospace;font-size:11px;box-shadow:0 4px 16px rgba(0,0,0,.1);white-space:nowrap;min-width:148px;`;
    containerRef.current.appendChild(tip);

    const onCross = (p) => {
      if (!p.point || !p.time || p.point.x < 0 || p.point.y < 0) { tip.style.display = 'none'; return; }
      const bar = p.seriesData.get(candles);
      if (!bar) { tip.style.display = 'none'; return; }
      const col = bar.close >= bar.open ? '#059669' : '#dc2626';
      const d = new Date(p.time * 1000);
      const str = `${String(d.getUTCDate()).padStart(2,'0')} ${d.toLocaleString('en',{month:'short',timeZone:'UTC'})} · ${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')}`;
      const w = containerRef.current?.clientWidth ?? 400;
      tip.style.left = `${p.point.x > w/2 ? p.point.x-170 : p.point.x+14}px`;
      tip.style.display = 'block';
      tip.style.borderLeft = `3px solid ${col}`;
      tip.innerHTML = `<div style="color:#9ca3af;font-size:10px;margin-bottom:5px">${str}</div>
        <div style="display:grid;grid-template-columns:12px 1fr;row-gap:3px;column-gap:10px;align-items:center">
          <span style="color:#9ca3af;font-size:10px">O</span><span style="color:${col}">₹${bar.open.toFixed(2)}</span>
          <span style="color:#9ca3af;font-size:10px">H</span><span style="color:#059669">₹${bar.high.toFixed(2)}</span>
          <span style="color:#9ca3af;font-size:10px">L</span><span style="color:#dc2626">₹${bar.low.toFixed(2)}</span>
          <span style="color:#9ca3af;font-size:10px">C</span><span style="color:${col};font-weight:700">₹${bar.close.toFixed(2)}</span>
        </div>`;
    };
    chart.subscribeCrosshairMove(onCross);

    const ro = new ResizeObserver(entries => {
      for (const e of entries) chart.applyOptions({ width: e.contentRect.width });
    });
    ro.observe(containerRef.current);

    // ── RSI chart ──────────────────────────────────────────────────────
    const rsiChart = createChart(rsiContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#9ca3af', fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
      },
      grid: { vertLines: { color: 'rgba(0,0,0,0.03)' }, horzLines: { color: 'rgba(0,0,0,0.03)' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderVisible: false, timeVisible: false, secondsVisible: false, rightOffset: 5 },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(0,0,0,0.12)', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#1f2937' },
        horzLine: { color: 'rgba(0,0,0,0.08)', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#1f2937' },
      },
      height: rsiH,
    });

    const rsiSeries = rsiChart.addLineSeries({
      color: '#a78bfa', lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: true, crosshairMarkerRadius: 3,
    });
    rsiSeries.createPriceLine({ price: 70, color: 'rgba(5,150,105,0.5)',   lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: '70' });
    rsiSeries.createPriceLine({ price: 50, color: 'rgba(156,163,175,0.35)',lineWidth: 1, lineStyle: LineStyle.Solid,  axisLabelVisible: false });
    rsiSeries.createPriceLine({ price: 45, color: 'rgba(234,179,8,0.6)',   lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: '45' });
    rsiSeries.createPriceLine({ price: 30, color: 'rgba(220,38,38,0.5)',   lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: '30' });

    rsiChartRef.current  = rsiChart;
    rsiSeriesRef.current = rsiSeries;

    const roRsi = new ResizeObserver(entries => {
      for (const e of entries) rsiChart.applyOptions({ width: e.contentRect.width });
    });
    roRsi.observe(rsiContainerRef.current);

    // ── Time scale sync (scroll/zoom both charts together) ─────────────
    chart.timeScale().subscribeVisibleTimeRangeChange(range => {
      if (syncingRef.current || !rsiChartRef.current) return;
      syncingRef.current = true;
      if (range) rsiChartRef.current.timeScale().setVisibleRange(range);
      syncingRef.current = false;
    });
    rsiChart.timeScale().subscribeVisibleTimeRangeChange(range => {
      if (syncingRef.current || !chartRef.current) return;
      syncingRef.current = true;
      if (range) chartRef.current.timeScale().setVisibleRange(range);
      syncingRef.current = false;
    });

    return () => {
      chart.unsubscribeCrosshairMove(onCross);
      if (tip.parentNode) tip.parentNode.removeChild(tip);
      ro.disconnect();
      roRsi.disconnect();
      chart.remove();
      rsiChart.remove();
      chartRef.current = candleRef.current = vwapRef.current = null;
      rsiChartRef.current = rsiSeriesRef.current = null;
    };
  }, []);

  // Load candles + RSI when symbol changes
  useEffect(() => {
    if (!candleRef.current || !symbol) return;
    try { candleRef.current.setMarkers([]); } catch (_) {}

    fetch(`/api/bt/candles/${encodeURIComponent(symbol)}`)
      .then(r => r.json())
      .then(data => {
        if (!candleRef.current) return;
        if (data.candles?.length) candleRef.current.setData(data.candles);
        if (data.vwap?.length)   vwapRef.current.setData(data.vwap);
        if (data.rsi?.length && rsiSeriesRef.current) rsiSeriesRef.current.setData(data.rsi);
        chartRef.current?.applyOptions({ rightPriceScale: { autoScale: true } });
        requestAnimationFrame(() => {
          if (!chartRef.current) return;
          const fd = focusDateRef.current;
          if (!fd || fd === 'ALL') {
            chartRef.current.timeScale().fitContent();
          } else {
            const base = new Date(fd + 'T00:00:00Z').getTime() / 1000;
            chartRef.current.timeScale().setVisibleRange({
              from: base + 9 * 3600 + 10 * 60,
              to:   base + 15 * 3600 + 25 * 60,
            });
          }
        });
      })
      .catch(() => {});
  }, [symbol]);

  // Update markers when backtest results change
  useEffect(() => {
    if (!candleRef.current) return;
    const filtered = (markers || []).filter(m => !m._symbol || m._symbol === symbol);
    try { candleRef.current.setMarkers(filtered); } catch (_) {}
  }, [markers, symbol]);

  // Zoom to a specific date or fit all
  useEffect(() => {
    if (!chartRef.current || !focusDate) return;
    requestAnimationFrame(() => {
      if (!chartRef.current) return;
      chartRef.current.applyOptions({ rightPriceScale: { autoScale: true } });
      if (focusDate === 'ALL') {
        chartRef.current.timeScale().fitContent();
      } else {
        const base = new Date(focusDate + 'T00:00:00Z').getTime() / 1000;
        chartRef.current.timeScale().setVisibleRange({
          from: base + 9 * 3600 + 10 * 60,
          to:   base + 15 * 3600 + 25 * 60,
        });
      }
    });
  }, [focusDate, symbol]);

  return (
    <div style={{ width: '100%', height: `${height}px` }}>
      <div ref={containerRef} style={{ width: '100%', height: `${mainH}px` }} />
      <div style={{ height: '4px', background: 'var(--border)' }} />
      <div style={{ position: 'relative' }}>
        <div style={{
          position: 'absolute', top: 3, left: 5, zIndex: 5,
          fontSize: '0.6rem', color: 'var(--muted)', fontFamily: 'var(--mono)',
          pointerEvents: 'none', letterSpacing: '0.02em',
        }}>
          RSI(14) &nbsp;·&nbsp; <span style={{ color: '#eab308' }}>— 45</span>
        </div>
        <div ref={rsiContainerRef} style={{ width: '100%', height: `${rsiH}px` }} />
      </div>
    </div>
  );
}


// ── Multi-select stock picker ──────────────────────────────────────────────────

function StockPicker({ symbols, selected, onChange }) {
  const [open,   setOpen]   = useState(false);
  const [search, setSearch] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const filtered = symbols.filter(s => s.toLowerCase().includes(search.toLowerCase()));
  const allSelected = filtered.length > 0 && filtered.every(s => selected.has(s));

  const toggle = (s) => {
    const next = new Set(selected);
    if (next.has(s)) next.delete(s); else next.add(s);
    onChange(next);
  };

  const toggleAll = () => {
    if (allSelected) {
      const next = new Set(selected);
      filtered.forEach(s => next.delete(s));
      onChange(next);
    } else {
      const next = new Set(selected);
      filtered.forEach(s => next.add(s));
      onChange(next);
    }
  };

  const clearAll = () => onChange(new Set());

  const label = selected.size === 0
    ? 'Select stocks'
    : selected.size === 1
    ? [...selected][0]
    : `${selected.size} stocks`;

  return (
    <div ref={ref} style={{ position: 'relative', flexShrink: 0 }}>
      {/* Trigger button */}
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.4rem',
          padding: '0.42rem 0.8rem',
          border: `1.5px solid ${open ? 'var(--green)' : selected.size > 0 ? 'var(--green-dim)' : 'var(--border2)'}`,
          borderRadius: '8px', cursor: 'pointer', minWidth: 150,
          background: selected.size > 0 ? 'var(--green-10)' : 'var(--surface2)',
          fontFamily: 'var(--mono)', fontSize: '0.85rem',
          fontWeight: selected.size > 0 ? 700 : 400,
          color: selected.size > 0 ? 'var(--green)' : 'var(--muted)',
          userSelect: 'none', transition: 'all 0.12s',
        }}
      >
        <span style={{ flex: 1 }}>{label}</span>
        {selected.size > 0 && (
          <span style={{
            background: 'var(--green)', color: '#fff',
            borderRadius: '10px', padding: '0 5px', fontSize: '0.65rem', fontWeight: 700,
          }}>
            {selected.size}
          </span>
        )}
        <span style={{ color: 'var(--muted)', fontSize: '0.65rem', marginLeft: '2px' }}>
          {open ? '▲' : '▼'}
        </span>
      </div>

      {/* Dropdown */}
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 999,
          background: 'var(--surface)', border: '1px solid var(--border2)',
          borderRadius: '10px', boxShadow: 'var(--shadow-lg)',
          width: 230, display: 'flex', flexDirection: 'column',
          maxHeight: 380, overflow: 'hidden',
        }}>
          {/* Search */}
          <div style={{ padding: '0.5rem 0.5rem 0.25rem' }}>
            <input
              autoFocus
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search symbol…"
              style={{
                width: '100%', padding: '0.38rem 0.65rem',
                border: '1px solid var(--border)', borderRadius: '6px',
                fontFamily: 'var(--mono)', fontSize: '0.8rem',
                outline: 'none', background: 'var(--bg)', color: 'var(--text)',
              }}
            />
          </div>

          {/* Select All / Clear row */}
          <div style={{
            display: 'flex', gap: '0.4rem', padding: '0.3rem 0.5rem',
            borderBottom: '1px solid var(--border)',
          }}>
            <button
              onClick={toggleAll}
              style={{
                flex: 1, padding: '0.3rem 0', fontSize: '0.72rem', fontWeight: 600,
                border: '1px solid var(--border)', borderRadius: '5px',
                background: allSelected ? 'var(--green-10)' : 'var(--surface2)',
                color: allSelected ? 'var(--green)' : 'var(--text)',
                cursor: 'pointer', fontFamily: 'var(--font)',
              }}
            >
              {allSelected ? `Deselect ${filtered.length === symbols.length ? 'All' : `(${filtered.length})`}` : `Select ${filtered.length === symbols.length ? 'All' : `(${filtered.length})`}`}
            </button>
            {selected.size > 0 && (
              <button
                onClick={clearAll}
                style={{
                  padding: '0.3rem 0.6rem', fontSize: '0.72rem',
                  border: '1px solid var(--border)', borderRadius: '5px',
                  background: 'var(--surface2)', color: 'var(--red)',
                  cursor: 'pointer', fontFamily: 'var(--font)',
                }}
              >
                Clear
              </button>
            )}
          </div>

          {/* Stock list with checkboxes */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {filtered.length === 0 && (
              <div style={{ padding: '0.6rem 0.75rem', color: 'var(--dim)', fontSize: '0.78rem' }}>
                No results
              </div>
            )}
            {filtered.map(s => {
              const checked = selected.has(s);
              return (
                <div
                  key={s}
                  onClick={() => toggle(s)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                    padding: '0.38rem 0.75rem', cursor: 'pointer',
                    background: checked ? 'var(--green-10)' : 'transparent',
                    transition: 'background 0.08s',
                  }}
                  onMouseEnter={e => { if (!checked) e.currentTarget.style.background = 'var(--surface2)'; }}
                  onMouseLeave={e => { if (!checked) e.currentTarget.style.background = 'transparent'; }}
                >
                  <div style={{
                    width: 14, height: 14, borderRadius: '3px', flexShrink: 0,
                    border: `1.5px solid ${checked ? 'var(--green)' : 'var(--border2)'}`,
                    background: checked ? 'var(--green)' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {checked && <span style={{ color: '#fff', fontSize: '9px', fontWeight: 900 }}>✓</span>}
                  </div>
                  <span style={{
                    fontFamily: 'var(--mono)', fontSize: '0.82rem',
                    color: checked ? 'var(--green)' : 'var(--text)',
                    fontWeight: checked ? 700 : 400,
                  }}>{s}</span>
                </div>
              );
            })}
          </div>

          {/* Footer */}
          <div style={{
            padding: '0.3rem 0.75rem 0.4rem', borderTop: '1px solid var(--border)',
            fontSize: '0.68rem', color: 'var(--dim)', display: 'flex', justifyContent: 'space-between',
          }}>
            <span>{symbols.length} stocks total</span>
            <span style={{ color: 'var(--green)', fontWeight: 600 }}>{selected.size} selected</span>
          </div>
        </div>
      )}
    </div>
  );
}


// ── BacktestLab ───────────────────────────────────────────────────────────────

export default function BacktestLab() {
  const [symbols,      setSymbols]      = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [serverError,  setServerError]  = useState(false);
  // Multi-select for backtest
  const [selected,     setSelected]     = useState(new Set());
  // Which stock is currently shown in chart
  const [chartSymbol,  setChartSymbol]  = useState(null);
  const [chartDates,   setChartDates]   = useState([]);
  const [chartDateIdx, setChartDateIdx] = useState(0);
  // Patterns + capital
  const [patterns,     setPatterns]     = useState(new Set(['B', 'ENG', 'HAM', 'MAR', 'HAM2S', 'FLAG', 'TRI', 'DTRI', 'VCNB', 'OPEN_RCL']));
  const [capital,      setCapital]      = useState(200000);
  // Backtest state
  const [running,      setRunning]      = useState(false);
  const [btError,      setBtError]      = useState(null);
  const [result,       setResult]       = useState(null);
  // Chart focus
  const [focusDate,    setFocusDate]    = useState('ALL');
  // Results table: which tab is active
  const [resTab,       setResTab]       = useState('trades');  // 'trades' | 'stocks' | 'patterns'

  // ── Server connection ──────────────────────────────────────────────────────
  const loadStocks = useCallback(() => {
    setLoading(true);
    setServerError(false);
    fetch('/api/bt/stocks')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => {
        const syms = d.symbols || [];
        setSymbols(syms);
        setLoading(false);
      })
      .catch(() => { setServerError(true); setLoading(false); });
  }, []);

  useEffect(() => { loadStocks(); }, [loadStocks]);

  // ── When chart symbol changes, load its dates ─────────────────────────────
  useEffect(() => {
    if (!chartSymbol) return;
    setFocusDate('ALL');
    fetch(`/api/bt/dates/${chartSymbol}`)
      .then(r => r.json())
      .then(d => {
        const ds = d.dates || [];
        setChartDates(ds);
        setChartDateIdx(ds.length > 0 ? ds.length - 1 : 0);
      })
      .catch(() => setChartDates([]));
  }, [chartSymbol]);

  // When selected changes, make sure chartSymbol is one of them (or first)
  useEffect(() => {
    if (selected.size === 0) { setChartSymbol(null); return; }
    if (!chartSymbol || !selected.has(chartSymbol)) {
      setChartSymbol([...selected][0]);
    }
  }, [selected]);

  // ── Build chart markers from backtest results ──────────────────────────────
  const chartMarkers = useMemo(() => {
    const trades = result?.trades;
    if (!trades?.length) return [];
    const out = [];
    trades.forEach(t => {
      const col = PAT_COLORS[t.pattern] || '#059669';
      out.push({ time: t.bar_ts, position: 'belowBar', color: col, shape: 'arrowUp', text: t.pattern, size: 1, _symbol: t.symbol });
      if (t.outcome === 'WIN')
        out.push({ time: t.exit_ts, position: 'aboveBar', color: '#059669', shape: 'circle', text: '✓', size: 0, _symbol: t.symbol });
      else if (t.outcome === 'SL')
        out.push({ time: t.exit_ts, position: 'aboveBar', color: '#dc2626', shape: 'circle', text: '✗', size: 0, _symbol: t.symbol });
    });
    return out.sort((a, b) => a.time - b.time);
  }, [result]);

  const summary = result?.summary;
  const trades  = result?.trades || [];
  const byPat   = summary?.by_pattern || {};
  const bySym   = summary?.by_symbol  || {};
  const chartDate = chartDates[chartDateIdx] ?? null;

  // ── Actions ────────────────────────────────────────────────────────────────
  const runBacktest = async () => {
    if (!selected.size || running) return;
    setRunning(true);
    setBtError(null);
    setResult(null);
    try {
      const res = await fetch('/api/bt/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: [...selected], patterns: [...patterns], capital }),
      });
      if (!res.ok) {
        let msg = `Server returned ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail) {
            msg = typeof body.detail === 'string'
              ? body.detail
              : JSON.stringify(body.detail);
          }
        } catch (_) {}
        throw new Error(msg);
      }
      const data = await res.json();
      setResult(data);
      setFocusDate('ALL');
    } catch (err) {
      setBtError(err.message || 'Request failed');
    } finally {
      setRunning(false);
    }
  };

  const togglePat = (p) => {
    setPatterns(prev => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      return next;
    });
  };

  const goDate = (delta) => {
    if (!chartDates.length) return;
    const next = Math.max(0, Math.min(chartDates.length - 1, chartDateIdx + delta));
    setChartDateIdx(next);
    setFocusDate(chartDates[next]);
  };

  // Click trade row → switch chart to that stock + date
  const jumpToTrade = (t) => {
    if (t.symbol !== chartSymbol) setChartSymbol(t.symbol);
    setFocusDate(t.date);
    // update dateIdx after dates load (handled by effect above) — best-effort
    const idx = chartDates.indexOf(t.date);
    if (idx >= 0) setChartDateIdx(idx);
  };

  const canRun = selected.size > 0 && !running && patterns.size > 0;

  const cardStyle = {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-sm)',
  };

  // ── Loading / error screens ────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--muted)' }}>
        <div style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>⟳</div>
        <div>Connecting to Backtest server…</div>
        <div style={{ fontSize: '0.75rem', marginTop: '0.4rem', fontFamily: 'var(--mono)', color: 'var(--dim)' }}>
          localhost:8002
        </div>
      </div>
    );
  }

  if (serverError) {
    return (
      <div style={{ padding: '2rem 1.5rem' }}>
        <div style={{
          background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.25)',
          borderRadius: 'var(--radius)', padding: '1.5rem 2rem', maxWidth: 560,
        }}>
          <div style={{ fontWeight: 700, color: 'var(--red)', marginBottom: '0.5rem' }}>
            Backtest server is not running
          </div>
          <div style={{ color: 'var(--muted)', fontSize: '0.82rem', marginBottom: '1rem', lineHeight: 1.6 }}>
            Open a new terminal in your project folder and run:
          </div>
          <div style={{
            background: '#1e1e2e', color: '#a6e3a1', fontFamily: 'var(--mono)',
            fontSize: '0.85rem', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1.2rem',
          }}>
            uvicorn backtest_server:app --port 8002
          </div>
          <button onClick={loadStocks} style={{
            padding: '0.5rem 1.2rem', background: 'var(--green)', color: '#fff',
            border: 'none', borderRadius: '8px', fontWeight: 700,
            fontSize: '0.82rem', cursor: 'pointer', fontFamily: 'var(--font)',
          }}>
            Retry connection
          </button>
        </div>
      </div>
    );
  }

  // ── Main UI ────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', padding: '1rem 1.5rem' }}>

      {/* ── Control bar ────────────────────────────────────────────────────── */}
      <div style={{
        ...cardStyle, padding: '0.7rem 1rem',
        display: 'flex', alignItems: 'center', gap: '0.85rem', flexWrap: 'wrap',
      }}>

        {/* Multi-select stock picker */}
        <StockPicker symbols={symbols} selected={selected} onChange={setSelected} />

        <div style={{ width: 1, height: 30, background: 'var(--border2)', flexShrink: 0 }} />

        {/* Chart stock switcher (only when 4+ selected; ≤3 stocks use split view) */}
        {selected.size > 3 && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexShrink: 0 }}>
              <span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>Chart</span>
              <select
                value={chartSymbol || ''}
                onChange={e => setChartSymbol(e.target.value)}
                style={{
                  padding: '0.3rem 0.5rem', border: '1px solid var(--border)',
                  borderRadius: '6px', background: 'var(--surface2)', color: 'var(--text)',
                  fontFamily: 'var(--mono)', fontSize: '0.8rem', outline: 'none', cursor: 'pointer',
                }}
              >
                {[...selected].map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div style={{ width: 1, height: 30, background: 'var(--border2)', flexShrink: 0 }} />
          </>
        )}

        {/* Date zoom navigator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexShrink: 0 }}>
          <span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>Jump to</span>
          <button
            onClick={() => goDate(-1)}
            disabled={chartDateIdx === 0 || !chartDates.length}
            style={{
              width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface2)',
              cursor: chartDateIdx === 0 ? 'default' : 'pointer', color: 'var(--text)', fontSize: '1rem',
              opacity: (chartDateIdx === 0 || !chartDates.length) ? 0.3 : 1,
            }}
          >‹</button>
          <span style={{
            fontFamily: 'var(--mono)', fontSize: '0.78rem', minWidth: 88, textAlign: 'center',
            color: chartDate ? 'var(--text)' : 'var(--dim)',
          }}>
            {chartDate || (chartSymbol ? 'loading…' : '—')}
          </span>
          <button
            onClick={() => goDate(1)}
            disabled={chartDateIdx >= chartDates.length - 1 || !chartDates.length}
            style={{
              width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface2)',
              cursor: chartDateIdx >= chartDates.length - 1 ? 'default' : 'pointer', color: 'var(--text)', fontSize: '1rem',
              opacity: (chartDateIdx >= chartDates.length - 1 || !chartDates.length) ? 0.3 : 1,
            }}
          >›</button>
          <span style={{ fontSize: '0.68rem', color: 'var(--dim)' }}>
            {chartDates.length > 0 ? `${chartDateIdx + 1}/${chartDates.length}` : '—'}
          </span>
          <button
            onClick={() => setFocusDate('ALL')}
            title="Zoom out to show full month"
            style={{
              marginLeft: '0.1rem', padding: '0.2rem 0.5rem', fontSize: '0.7rem',
              border: '1px solid var(--border)', borderRadius: '5px', background: 'var(--surface2)',
              cursor: 'pointer', color: 'var(--muted)', fontFamily: 'var(--mono)',
            }}
          >Fit all</button>
        </div>

        <div style={{ width: 1, height: 30, background: 'var(--border2)', flexShrink: 0 }} />

        {/* Pattern toggles */}
        <div style={{ display: 'flex', gap: '0.28rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.7rem', color: 'var(--muted)', marginRight: '0.1rem' }}>Patterns</span>
          {ALL_PATTERNS.map(p => {
            const active = patterns.has(p);
            return (
              <button key={p} onClick={() => togglePat(p)} title={active ? `Disable ${p}` : `Enable ${p}`}
                style={{
                  padding: '0.25rem 0.58rem', borderRadius: '6px', cursor: 'pointer',
                  fontFamily: 'var(--mono)', fontWeight: 700, fontSize: '0.73rem',
                  border: `1.5px solid ${active ? PAT_COLORS[p] : 'var(--border)'}`,
                  background: active ? PAT_COLORS[p] + '15' : 'var(--surface2)',
                  color: active ? PAT_COLORS[p] : 'var(--dim)',
                  textDecoration: active ? 'none' : 'line-through',
                  transition: 'all 0.12s',
                }}
              >{p}</button>
            );
          })}
        </div>

        <div style={{ width: 1, height: 30, background: 'var(--border2)', flexShrink: 0 }} />

        {/* Capital */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexShrink: 0 }}>
          <span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>Capital</span>
          <input
            type="number" value={capital}
            onChange={e => setCapital(Number(e.target.value) || 0)}
            style={{
              width: 88, padding: '0.35rem 0.5rem', border: '1px solid var(--border)',
              borderRadius: '6px', fontFamily: 'var(--mono)', fontSize: '0.8rem',
              background: 'var(--surface2)', color: 'var(--text)', outline: 'none',
            }}
          />
          <span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>₹</span>
        </div>

        {/* Run button */}
        <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
          <button
            onClick={runBacktest}
            disabled={!canRun}
            title={!selected.size ? 'Select at least one stock' : patterns.size === 0 ? 'Enable at least one pattern' : ''}
            style={{
              padding: '0.45rem 1.15rem',
              background: canRun ? 'var(--green)' : 'var(--green-dim)',
              color: '#fff', border: 'none', borderRadius: '8px',
              fontWeight: 700, fontSize: '0.82rem',
              cursor: canRun ? 'pointer' : 'not-allowed',
              fontFamily: 'var(--font)',
              display: 'flex', alignItems: 'center', gap: '0.4rem',
              opacity: canRun ? 1 : 0.5,
            }}
          >
            {running ? (
              <>
                <span style={{
                  display: 'inline-block', width: 10, height: 10,
                  border: '1.5px solid rgba(255,255,255,0.3)', borderTopColor: '#fff',
                  borderRadius: '50%', animation: 'spin 0.8s linear infinite',
                }} />
                Running…
              </>
            ) : `▶ Run${selected.size > 1 ? ` (${selected.size})` : ''}`}
          </button>
        </div>
      </div>

      {/* ── Error ──────────────────────────────────────────────────────────── */}
      {btError && (
        <div style={{
          background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.25)',
          borderRadius: 'var(--radius-sm)', padding: '0.65rem 1rem',
          fontSize: '0.8rem', color: 'var(--red)', fontFamily: 'var(--mono)',
        }}>
          Run failed: {btError}
        </div>
      )}

      {/* ── Chart ──────────────────────────────────────────────────────────── */}
      {selected.size >= 2 && selected.size <= 3 ? (
        /* Split view: 2 or 3 stocks side by side */
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${selected.size}, 1fr)`,
          gap: '0.75rem',
        }}>
          {[...selected].map(sym => {
            const sigCount = chartMarkers.filter(m => m._symbol === sym && m.shape === 'arrowUp').length;
            const h = selected.size === 3 ? 340 : 380;
            return (
              <div key={sym} style={{ ...cardStyle, overflow: 'hidden' }}>
                <div style={{
                  padding: '0.5rem 0.75rem 0.35rem', borderBottom: '1px solid var(--border)',
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                }}>
                  <span style={{ fontWeight: 700, fontFamily: 'var(--mono)', fontSize: '0.85rem' }}>{sym}</span>
                  {chartDates.length > 0 && (
                    <span style={{ color: 'var(--muted)', fontSize: '0.68rem' }}>
                      {chartDates.length}d
                    </span>
                  )}
                  <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.65rem', color: 'var(--muted)' }}>
                    <span style={{ width: 12, height: 2, background: '#7c3aed', display: 'inline-block', borderRadius: 1 }} />
                    {sigCount > 0 && (
                      <span style={{ color: 'var(--green)' }}>{sigCount}✓</span>
                    )}
                  </span>
                </div>
                <BtChart symbol={sym} markers={chartMarkers} focusDate={focusDate} height={h} />
              </div>
            );
          })}
        </div>
      ) : (
        /* Single chart (1 stock, or 3+ with switcher dropdown) */
        <div style={{ ...cardStyle, overflow: 'hidden' }}>
          <div style={{
            padding: '0.55rem 1rem 0.4rem', borderBottom: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap',
          }}>
            <span style={{ fontWeight: 700, fontFamily: 'var(--mono)', fontSize: '0.9rem' }}>
              {chartSymbol || 'Select stocks to view chart'}
            </span>
            {chartDates.length > 0 && (
              <span style={{ color: 'var(--muted)', fontSize: '0.75rem' }}>
                {chartDates[0]} – {chartDates[chartDates.length - 1]} · {chartDates.length} days · 10-min
              </span>
            )}
            <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.7rem', color: 'var(--muted)' }}>
              <span style={{ width: 16, height: 2, background: '#7c3aed', display: 'inline-block', borderRadius: 1 }} /> VWAP
              {chartMarkers.filter(m => m._symbol === chartSymbol).length > 0 && (
                <span style={{ color: 'var(--green)' }}>
                  · {chartMarkers.filter(m => m._symbol === chartSymbol && m.shape === 'arrowUp').length} signal{chartMarkers.filter(m => m._symbol === chartSymbol && m.shape === 'arrowUp').length !== 1 ? 's' : ''} marked
                </span>
              )}
            </span>
          </div>

          {chartSymbol ? (
            <BtChart symbol={chartSymbol} markers={chartMarkers} focusDate={focusDate} />
          ) : (
            <div style={{ padding: '4rem', textAlign: 'center', color: 'var(--muted)', fontSize: '0.85rem' }}>
              Select one or more stocks from the dropdown, then use the chart to explore their candles
            </div>
          )}
        </div>
      )}

      {/* ── Running indicator ──────────────────────────────────────────────── */}
      {running && (
        <div style={{ ...cardStyle, padding: '1.25rem', textAlign: 'center', color: 'var(--muted)', fontSize: '0.85rem' }}>
          <span style={{
            display: 'inline-block', width: 14, height: 14, borderRadius: '50%',
            border: '2px solid var(--border)', borderTopColor: 'var(--green)',
            animation: 'spin 0.8s linear infinite', marginRight: '0.6rem', verticalAlign: 'middle',
          }} />
          Running backtest on {selected.size} stock{selected.size !== 1 ? 's' : ''} across {[...selected].map(() => chartDates.length).reduce((a, b) => a + b, 0) || '…'} days…
        </div>
      )}

      {/* ── Results ────────────────────────────────────────────────────────── */}
      {!running && summary && (
        <>
          {/* Stats */}
          <div style={{ display: 'flex', gap: '0.7rem', flexWrap: 'wrap' }}>
            <StatCard label="Stocks tested" value={selected.size} />
            <StatCard label="Trades found" value={summary.total} />
            <StatCard label="Wins" value={summary.wins} color="var(--green)" />
            <StatCard label="SL hits" value={summary.losses} color="var(--red)" />
            <StatCard
              label="Win Rate"
              value={`${summary.win_rate}%`}
              color={summary.win_rate >= 40 ? 'var(--green)' : summary.win_rate >= 25 ? 'var(--gold)' : 'var(--red)'}
              sub={patterns.has('OPEN_RCL') || patterns.has('VCNB') ? 'breakeven ~33% (2:1)' : '25% = breakeven (3:1)'}
            />
            <StatCard
              label="Net P&L"
              value={`${summary.total_pnl >= 0 ? '+' : '−'}₹${Math.abs(summary.total_pnl).toLocaleString('en-IN')}`}
              color={summary.total_pnl >= 0 ? 'var(--green)' : 'var(--red)'}
              sub={`per ₹${capital.toLocaleString('en-IN')}`}
            />
          </div>

          {/* Results tabs */}
          <div style={cardStyle}>
            {/* Tab header */}
            <div style={{
              display: 'flex', borderBottom: '1px solid var(--border)',
              padding: '0 1rem', gap: 0,
            }}>
              {[
                ['trades',   `Trades (${trades.length})`],
                ['stocks',   `By Stock (${Object.keys(bySym).length})`],
                ['patterns', `By Pattern (${Object.keys(byPat).length})`],
              ].map(([id, label]) => (
                <button key={id} onClick={() => setResTab(id)} style={{
                  padding: '0.55rem 0.9rem', border: 'none', background: 'transparent',
                  borderBottom: resTab === id ? '2px solid var(--green)' : '2px solid transparent',
                  color: resTab === id ? 'var(--green)' : 'var(--muted)',
                  fontFamily: 'var(--font)', fontWeight: resTab === id ? 600 : 400,
                  fontSize: '0.78rem', cursor: 'pointer', transition: 'all 0.12s',
                }}>
                  {label}
                </button>
              ))}
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', padding: '0 0.25rem' }}>
                <span style={{ fontSize: '0.68rem', color: 'var(--dim)' }}>
                  {resTab === 'trades' ? 'click row to view on chart' : ''}
                </span>
              </div>
            </div>

            {/* Trades tab */}
            {resTab === 'trades' && (
              trades.length > 0 ? (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.79rem', fontFamily: 'var(--mono)' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--dim)', fontSize: '0.69rem' }}>
                        {(selected.size > 1 ? ['Symbol'] : []).concat(['Date', 'Pat', 'Time', 'Entry ₹', 'SL ₹', 'Target ₹', 'Outcome', 'Exit', 'P&L ₹']).map(h => (
                          <th key={h} style={{ padding: '0.42rem 0.75rem', textAlign: 'left', fontWeight: 500 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((t, i) => {
                        const isActive = t.symbol === chartSymbol && t.date === chartDate;
                        return (
                          <tr key={i} onClick={() => jumpToTrade(t)}
                            style={{
                              borderBottom: '1px solid var(--border)', cursor: 'pointer',
                              background: isActive ? 'var(--green-10)' : 'transparent',
                            }}
                            onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--surface2)'; }}
                            onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                          >
                            {selected.size > 1 && (
                              <td style={{ padding: '0.4rem 0.75rem', fontWeight: 700, color: t.symbol === chartSymbol ? 'var(--green)' : 'var(--text)' }}>{t.symbol}</td>
                            )}
                            <td style={{ padding: '0.4rem 0.75rem', color: 'var(--muted)', fontSize: '0.73rem' }}>{t.date}</td>
                            <td style={{ padding: '0.4rem 0.75rem' }}><PatBadge name={t.pattern} /></td>
                            <td style={{ padding: '0.4rem 0.75rem', color: 'var(--muted)' }}>{t.entry_time}</td>
                            <td style={{ padding: '0.4rem 0.75rem' }}>{t.entry.toFixed(2)}</td>
                            <td style={{ padding: '0.4rem 0.75rem', color: 'var(--red)' }}>{t.sl.toFixed(2)}</td>
                            <td style={{ padding: '0.4rem 0.75rem', color: 'var(--gold)' }}>{t.target.toFixed(2)}</td>
                            <td style={{ padding: '0.4rem 0.75rem' }}><OutcomeBadge outcome={t.outcome} /></td>
                            <td style={{ padding: '0.4rem 0.75rem', color: 'var(--muted)' }}>{t.exit_time}</td>
                            <td style={{ padding: '0.4rem 0.75rem', fontWeight: 700, color: t.pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
                              {t.pnl >= 0 ? '+' : '−'}₹{Math.abs(t.pnl).toLocaleString('en-IN')}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--muted)', fontSize: '0.85rem' }}>
                  No pattern signals found with the selected patterns.
                </div>
              )
            )}

            {/* By Stock tab */}
            {resTab === 'stocks' && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', fontFamily: 'var(--mono)' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--dim)', fontSize: '0.7rem' }}>
                      {['Stock', 'Trades', 'Wins', 'SL', 'Win Rate', 'Net P&L'].map(h => (
                        <th key={h} style={{ padding: '0.45rem 0.9rem', textAlign: 'left', fontWeight: 500 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(bySym)
                      .sort((a, b) => b[1].pnl - a[1].pnl)
                      .map(([sym, s]) => (
                        <tr key={sym}
                          onClick={() => { setChartSymbol(sym); setFocusDate('ALL'); }}
                          style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer', background: sym === chartSymbol ? 'var(--green-10)' : 'transparent' }}
                          onMouseEnter={e => { if (sym !== chartSymbol) e.currentTarget.style.background = 'var(--surface2)'; }}
                          onMouseLeave={e => { if (sym !== chartSymbol) e.currentTarget.style.background = 'transparent'; }}
                        >
                          <td style={{ padding: '0.45rem 0.9rem', fontWeight: 700, color: sym === chartSymbol ? 'var(--green)' : 'var(--text)' }}>{sym}</td>
                          <td style={{ padding: '0.45rem 0.9rem' }}>{s.trades}</td>
                          <td style={{ padding: '0.45rem 0.9rem', color: 'var(--green)' }}>{s.wins}</td>
                          <td style={{ padding: '0.45rem 0.9rem', color: 'var(--red)' }}>{s.losses}</td>
                          <td style={{ padding: '0.45rem 0.9rem', fontWeight: 700, color: s.wr >= 40 ? 'var(--green)' : s.wr >= 25 ? 'var(--gold)' : 'var(--red)' }}>
                            {s.wr}%
                          </td>
                          <td style={{ padding: '0.45rem 0.9rem', fontWeight: 600, color: s.pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
                            {s.pnl >= 0 ? '+' : '−'}₹{Math.abs(s.pnl).toLocaleString('en-IN')}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* By Pattern tab */}
            {resTab === 'patterns' && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', fontFamily: 'var(--mono)' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--dim)', fontSize: '0.7rem' }}>
                      {['Pattern', 'Trades', 'Wins', 'SL', 'Win Rate', 'Net P&L'].map(h => (
                        <th key={h} style={{ padding: '0.45rem 0.9rem', textAlign: 'left', fontWeight: 500 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(byPat).map(([p, s]) => (
                      <tr key={p} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '0.45rem 0.9rem' }}><PatBadge name={p} /></td>
                        <td style={{ padding: '0.45rem 0.9rem' }}>{s.trades}</td>
                        <td style={{ padding: '0.45rem 0.9rem', color: 'var(--green)' }}>{s.wins}</td>
                        <td style={{ padding: '0.45rem 0.9rem', color: 'var(--red)' }}>{s.losses}</td>
                        <td style={{ padding: '0.45rem 0.9rem', fontWeight: 700, color: s.wr >= 40 ? 'var(--green)' : s.wr >= 25 ? 'var(--gold)' : 'var(--red)' }}>
                          {s.wr}%
                        </td>
                        <td style={{ padding: '0.45rem 0.9rem', fontWeight: 600, color: s.pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
                          {s.pnl >= 0 ? '+' : '−'}₹{Math.abs(s.pnl).toLocaleString('en-IN')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
