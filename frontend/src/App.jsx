import { useState, useEffect, useCallback } from 'react';
import FilterPanel from './components/FilterPanel.jsx';
import SignalCard from './components/SignalCard.jsx';
import SummaryTable from './components/SummaryTable.jsx';
import TestTable from './components/TestTable.jsx';

// ── TejToro Bull Logo ─────────────────────────────────────────────────────────
function TejToroLogo({ size = 32 }) {
  return (
    <svg
      width={size} height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Rounded square base */}
      <rect width="32" height="32" rx="8" fill="#059669"/>

      {/* Left horn — curves up and outward to the left */}
      <path
        d="M13 18 Q8.5 13 11 7"
        stroke="white" strokeWidth="2.4" strokeLinecap="round" fill="none"
      />
      {/* Right horn — curves up and outward to the right */}
      <path
        d="M19 18 Q23.5 13 21 7"
        stroke="white" strokeWidth="2.4" strokeLinecap="round" fill="none"
      />

      {/* Muzzle / snout oval */}
      <ellipse cx="16" cy="23" rx="6" ry="4.5" fill="white"/>

      {/* Left nostril */}
      <circle cx="13.6" cy="24" r="1.25" fill="#059669"/>
      {/* Right nostril */}
      <circle cx="18.4" cy="24" r="1.25" fill="#059669"/>

      {/* Eyes — small filled dots */}
      <circle cx="12.8" cy="18.5" r="0.9" fill="white"/>
      <circle cx="19.2" cy="18.5" r="0.9" fill="white"/>
    </svg>
  );
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function LiveClock({ serverTime }) {
  const [display, setDisplay] = useState(serverTime || '--:--:--');
  useEffect(() => { if (serverTime) setDisplay(serverTime); }, [serverTime]);
  return <span className="header-time mono">{display} IST</span>;
}

// ── Header ────────────────────────────────────────────────────────────────────
function Header({
  universe, serverTime, marketOpen,
  scanning, scanTime, resultCount, signalCount,
  onScan, onClear, filterOpen, onToggleFilter,
}) {
  return (
    <header className="header">
      <div className="header-inner">
        <div className="header-brand">
          <TejToroLogo size={34} />
          <div>
            <div className="header-title" style={{ fontSize: '1rem', letterSpacing: '0.01em' }}>
              Tej<span style={{ color: 'var(--green)', fontWeight: 800 }}>Toro</span>
            </div>
            <div className="header-subtitle">VWAP Convergence Scanner · NSE · 10-min</div>
          </div>
        </div>

        <div className="header-divider" />

        <div className="header-stats">
          <div className="hstat">
            <div className="hstat-val">{universe}</div>
            <div className="hstat-label">Universe</div>
          </div>
          {scanTime && (
            <>
              <div className="hstat">
                <div className="hstat-val green">{resultCount}</div>
                <div className="hstat-label">Passed</div>
              </div>
              <div className="hstat">
                <div className="hstat-val gold">{signalCount}</div>
                <div className="hstat-label">Signals</div>
              </div>
            </>
          )}
          <div
            className={`market-badge ${marketOpen ? 'live' : 'closed'}`}
          >
            {marketOpen && <span className="market-dot" />}
            {marketOpen ? 'MARKET LIVE' : 'MARKET CLOSED'}
          </div>
        </div>

        <LiveClock serverTime={serverTime} />

        <div className="header-actions">
          <button className="btn btn-ghost" onClick={onToggleFilter}>
            {filterOpen ? '▲ Filters' : '▼ Filters'}
          </button>
          <button
            className="btn btn-primary"
            onClick={onScan}
            disabled={scanning}
          >
            {scanning ? (
              <><span className="scan-spinner" style={{display:'inline-block',width:'10px',height:'10px',border:'1.5px solid rgba(0,255,159,0.2)',borderTopColor:'var(--green)',borderRadius:'50%',animation:'spin 0.8s linear infinite'}} /> Scanning…</>
            ) : '⟳ Run Scan'}
          </button>
          {scanTime && (
            <button className="btn btn-danger" onClick={onClear}>✕ Clear</button>
          )}
        </div>
      </div>
    </header>
  );
}

// ── Scan progress ─────────────────────────────────────────────────────────────
function ScanProgress({ done, total }) {
  const pct = total > 0 ? (done / total) * 100 : 0;
  return (
    <div className="scan-progress">
      <div className="scan-progress-top">
        <div className="scan-progress-label">
          Scanning universe… <span>{done}</span> / <span>{total}</span>
        </div>
        <div className="scan-spinner" />
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${pct === 0 ? 'shimmer' : ''}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHead({ title, color = 'green' }) {
  return (
    <div className="section-head">
      <div className={`section-dot ${color}`} />
      <div className="section-title">{title}</div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────
function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-bull">🐂</div>
      <div className="empty-title">TejToro is ready</div>
      <div className="empty-sub">
        Click Run Scan to find VWAP convergence setups · Best: 9:45 AM – 11:30 AM
      </div>
    </div>
  );
}

function NoResults() {
  return (
    <div className="empty-state">
      <div className="empty-bull">🐻</div>
      <div className="empty-title">No stocks passed all 7 filters</div>
      <div className="empty-sub">Results change every 10 minutes · Try again shortly</div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [results,        setResults]        = useState([]);
  const [scanTime,       setScanTime]       = useState(null);
  const [scanning,       setScanning]       = useState(false);
  const [scanProgress,   setScanProgress]   = useState({ done: 0, total: 0 });
  const [live,           setLive]           = useState({ prices: {}, marketOpen: false, serverTime: '' });
  const [universe,       setUniverse]       = useState(0);
  const [filterOpen,     setFilterOpen]     = useState(false);
  const [lastPriceRefresh, setLastPriceRefresh] = useState(null);
  const [testMode,       setTestMode]       = useState(false);

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/results').then(r => r.json()),
    ]).then(([status, rd]) => {
      setUniverse(status.universe);
      setTestMode(!!status.test_mode);
      setLive(l => ({ ...l, marketOpen: status.market_open, serverTime: status.server_time }));
      setResults(rd.results || []);
      setScanTime(rd.scan_time);
      if (status.scanning) {
        setScanning(true);
        setScanProgress({ done: status.scan_progress, total: status.scan_total });
      }
    }).catch(() => {});
  }, []);

  // ── Re-fetch results every 60 s to pick up server-side signal re-checks ──
  useEffect(() => {
    if (!scanTime || scanning) return;
    const id = setInterval(() => {
      fetch('/api/results')
        .then(r => r.json())
        .then(rd => { if (rd.results) setResults(rd.results); })
        .catch(() => {});
    }, 60000);
    return () => clearInterval(id);
  }, [scanTime, scanning]);

  // ── Live prices — poll every 5 s ─────────────────────────────────────────
  useEffect(() => {
    const go = () =>
      fetch('/api/live')
        .then(r => r.json())
        .then(d => {
          setLive({ prices: d.prices || {}, marketOpen: d.market_open, serverTime: d.server_time });
          if (Object.keys(d.prices || {}).length > 0) setLastPriceRefresh(new Date());
        })
        .catch(() => {});

    go();
    const id = setInterval(go, 5000);
    return () => clearInterval(id);
  }, []);

  // ── Poll scan status every 1.5 s while scanning ──────────────────────────
  useEffect(() => {
    if (!scanning) return;
    const poll = () =>
      fetch('/api/status')
        .then(r => r.json())
        .then(d => {
          setScanProgress({ done: d.scan_progress, total: d.scan_total });
          if (!d.scanning) {
            setScanning(false);
            fetch('/api/results').then(r => r.json()).then(rd => {
              setResults(rd.results || []);
              setScanTime(rd.scan_time);
            });
          }
        })
        .catch(() => {});

    const id = setInterval(poll, 1500);
    return () => clearInterval(id);
  }, [scanning]);

  // ── Actions ───────────────────────────────────────────────────────────────
  const handleScan = useCallback(async () => {
    setScanning(true);
    setResults([]);
    setScanTime(null);
    setScanProgress({ done: 0, total: 0 });
    await fetch('/api/scan/start', { method: 'POST' }).catch(() => {});
  }, []);

  const handleClear = useCallback(async () => {
    await fetch('/api/clear', { method: 'POST' }).catch(() => {});
    setResults([]);
    setScanTime(null);
  }, []);

  const SIGNAL_CUTOFF = '10:15';

  const allFired = results.filter(r => r.entry_signal);
  const watching = results.filter(r => !r.entry_signal);

  // In test mode: sort by sim outcome (target first), no cap
  // In prod mode: sort by confidence, cap at 10
  const fired = [...allFired]
    .sort((a, b) => {
      if (testMode) {
        const order = { TARGET_HIT: 0, IN_TRADE: 1, SL_HIT: 2 };
        return (order[a.sim?.outcome] ?? 9) - (order[b.sim?.outcome] ?? 9);
      }
      return b.confidence - a.confidence;
    })
    .slice(0, testMode ? 9999 : 10)
    .map(r => ({
      ...r,
      isLate: live.marketOpen && (r.entry_signal.entry_time || '') > SIGNAL_CUTOFF,
    }));

  const lateCount = fired.filter(r => r.isLate).length;

  return (
    <div className="app">
      <Header
        universe={universe}
        serverTime={live.serverTime}
        marketOpen={live.marketOpen}
        scanning={scanning}
        scanTime={scanTime}
        resultCount={results.length}
        signalCount={allFired.length}
        onScan={handleScan}
        onClear={handleClear}
        filterOpen={filterOpen}
        onToggleFilter={() => setFilterOpen(f => !f)}
      />

      {filterOpen && <FilterPanel />}

      <div className="main-content">
        {scanning && (
          <ScanProgress done={scanProgress.done} total={scanProgress.total} />
        )}

        {scanTime && !scanning && (
          <div className="status-bar">
            <span>
              Scan at <b>{scanTime}</b> ·{' '}
              <span className="green">{results.length} passed</span> ·{' '}
              <span className="green">{fired.length} signal{fired.length !== 1 ? 's' : ''}</span>
            </span>
            {live.marketOpen ? (
              <span className="live-indicator">
                <span className="live-dot" />
                LIVE · {live.serverTime}
                {lastPriceRefresh && (
                  <span style={{ marginLeft: '0.5rem', opacity: 0.7 }}>
                    · prices at {lastPriceRefresh.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                )}
              </span>
            ) : (
              <span className="muted">Market Closed · {live.serverTime}</span>
            )}
          </div>
        )}

        {!scanning && !scanTime && <EmptyState />}
        {!scanning && scanTime && results.length === 0 && <NoResults />}

        {/* ── TEST MODE BANNER ─────────────────────────────────────────── */}
        {testMode && (
          <div style={{
            margin: '0 0 1rem 0', padding: '0.75rem 1.1rem',
            background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(124,58,237,0.35)',
            borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '0.6rem',
            fontSize: '0.78rem', color: '#a78bfa', fontFamily: 'var(--mono)',
          }}>
            <span style={{ fontSize: '1rem' }}>🧪</span>
            <span>
              <b>Test Mode</b> — No filters applied. All {universe} stocks scanned for Pattern B/C.
              Signals shown from 9:15 AM to now. Sim P&L uses ₹2L capital per trade.
            </span>
          </div>
        )}

        {/* ── TESTING WARNING ───────────────────────────────────────────── */}
        {lateCount > 0 && (
          <div style={{
            margin: '0 0 1rem 0',
            padding: '0.75rem 1.1rem',
            background: 'rgba(234,179,8,0.08)',
            border: '1px solid rgba(234,179,8,0.35)',
            borderRadius: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '0.6rem',
            fontSize: '0.78rem',
            color: '#92400e',
            fontFamily: 'var(--mono)',
          }}>
            <span style={{ fontSize: '1rem' }}>⚠</span>
            <span>
              <b>Testing mode</b> — {lateCount} signal{lateCount > 1 ? 's' : ''} outside the valid window (after {SIGNAL_CUTOFF}).
              These are shown for review only. In live trading, only signals before {SIGNAL_CUTOFF} are acted on.
              Signals marked <b>LATE</b> may not represent real opportunities.
            </span>
          </div>
        )}

        {/* ── BUY SIGNALS ───────────────────────────────────────────────── */}
        {fired.length > 0 && (
          <div className="page-section">
            <SectionHead
              title={`Buy Signals — ${fired.length} total · sorted by confidence`}
              color="green"
            />
            {fired.map(r => (
              <SignalCard
                key={r.symbol}
                result={r}
                ltp={live.prices[r.instrument_key] ?? null}
                marketOpen={live.marketOpen}
                isLate={r.isLate}
              />
            ))}
          </div>
        )}

        {fired.length === 0 && watching.length > 0 && (
          <div className="page-section">
            <div className="watching-banner">
              🐻 No buy signals yet — {watching.length} stocks watching for Pattern B (VWAP reclaim) or Pattern C (breakout retest)
            </div>
          </div>
        )}

        {/* ── TEST TABLE (test mode only) ───────────────────────────────── */}
        {testMode && fired.length > 0 && (
          <div className="page-section">
            <SectionHead title={`Backtest Results — ${fired.length} signals today`} color="purple" />
            <TestTable results={results} />
          </div>
        )}

        {/* ── SUMMARY TABLE (production mode only) ─────────────────────── */}
        {!testMode && results.length > 0 && (
          <div className="page-section">
            <SectionHead title={`All Passing Stocks — ${results.length} total`} color="purple" />
            <SummaryTable
              results={results}
              prices={live.prices}
              marketOpen={live.marketOpen}
            />
          </div>
        )}
      </div>
    </div>
  );
}
