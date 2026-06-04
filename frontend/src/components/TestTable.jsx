const fmt2 = (n) =>
  n != null ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';

// ── Pattern metadata — display name + colours for each pattern code ──────────
const PATTERN_META = {
  B:     { label: 'VWAP Reclaim',      color: '#60a5fa', bg: 'rgba(37,99,235,0.15)'   },
  C:     { label: 'Breakout Retest',   color: '#a78bfa', bg: 'rgba(124,58,237,0.15)'  },
  ENG:   { label: 'Bullish Engulfing', color: '#34d399', bg: 'rgba(5,150,105,0.15)'   },
  HAM:   { label: 'Hammer/Pin Bar',    color: '#fbbf24', bg: 'rgba(217,119,6,0.15)'   },
  MAR:   { label: 'Marubozu Reclaim',  color: '#f472b6', bg: 'rgba(219,39,119,0.15)'  },
  STAR:  { label: 'Morning Star',      color: '#fb923c', bg: 'rgba(234,88,12,0.15)'   },
  HAM2S: { label: 'Hammer −2σ',        color: '#fcd34d', bg: 'rgba(252,211,77,0.15)'  },
  BW:    { label: 'Band Walk +1σ',     color: '#4ade80', bg: 'rgba(74,222,128,0.15)'  },
  SQZ:   { label: 'Squeeze Break',     color: '#c084fc', bg: 'rgba(192,132,252,0.15)' },
  FLAG:     { label: 'Bull Flag',       color: '#f59e0b', bg: 'rgba(245,158,11,0.15)'  },
  TRI:      { label: 'Asc Triangle',   color: '#06b6d4', bg: 'rgba(6,182,212,0.15)'   },
  DTRI:     { label: 'Desc Triangle',  color: '#f97316', bg: 'rgba(249,115,22,0.15)'  },
  VCNB:     { label: 'VWAP Consol BRK', color: '#10b981', bg: 'rgba(16,185,129,0.15)' },
  OPEN_RCL: { label: 'Opening Reclaim', color: '#e879f9', bg: 'rgba(232,121,249,0.15)' },
};

const OUTCOME_META = {
  TARGET_HIT: { label: '🎯 TARGET HIT', color: 'var(--green)', bg: 'var(--green-10)' },
  SL_HIT:     { label: '🛑 SL HIT',     color: 'var(--red)',   bg: 'var(--red-10)'   },
  IN_TRADE:   { label: '📈 IN TRADE',   color: 'var(--blue)',  bg: 'var(--blue-10)'  },
};

function PatternBadge({ pattern }) {
  const m = PATTERN_META[pattern] || { label: pattern, color: 'var(--dim)', bg: 'transparent' };
  return (
    <span style={{
      fontSize: '0.62rem', fontWeight: 700, padding: '2px 8px', borderRadius: '999px',
      background: m.bg, color: m.color, fontFamily: 'var(--mono)', whiteSpace: 'nowrap',
    }}>
      {m.label}
    </span>
  );
}

function OutcomeBadge({ outcome }) {
  const m = OUTCOME_META[outcome] || { label: outcome, color: 'var(--dim)', bg: 'transparent' };
  return (
    <span style={{
      fontSize: '0.62rem', fontWeight: 700, padding: '3px 9px', borderRadius: '999px',
      background: m.bg, color: m.color, fontFamily: 'var(--mono)', whiteSpace: 'nowrap',
    }}>
      {m.label}
    </span>
  );
}

export default function TestTable({ results, prices = {} }) {
  if (!results || results.length === 0) return null;

  const signals = results.filter(r => r.entry_signal && r.sim);

  // For IN TRADE rows, use live LTP if available
  const livePnl = (r) => {
    const ltp = prices[r.instrument_key];
    if (!ltp || r.sim.outcome !== 'IN_TRADE') return r.sim.pnl;
    return Math.round((ltp - r.entry_signal.entry) * r.sim.shares);
  };

  const livePnlPct = (r) => {
    const ltp = prices[r.instrument_key];
    if (!ltp || r.sim.outcome !== 'IN_TRADE') return r.sim.pnl_pct;
    return +((ltp - r.entry_signal.entry) / r.entry_signal.entry * 100).toFixed(2);
  };

  const liveExitPrice = (r) => {
    const ltp = prices[r.instrument_key];
    if (!ltp || r.sim.outcome !== 'IN_TRADE') return r.sim.exit_price;
    return ltp;
  };

  const totalPnl = signals.reduce((s, r) => s + livePnl(r), 0);
  const wins     = signals.filter(r => r.sim.outcome === 'TARGET_HIT').length;
  const losses   = signals.filter(r => r.sim.outcome === 'SL_HIT').length;
  const inTrade  = signals.filter(r => r.sim.outcome === 'IN_TRADE').length;
  const winRate  = signals.length > 0 ? (wins / signals.length * 100).toFixed(0) : 0;

  // ── Per-pattern grouping ──────────────────────────────────────────────────
  const groups = {};
  for (const r of signals) {
    const pat = r.entry_signal.pattern;
    if (!groups[pat]) groups[pat] = { signals: [], pnl: 0, wins: 0, losses: 0, inTrade: 0 };
    groups[pat].signals.push(r);
    groups[pat].pnl += livePnl(r);
    if (r.sim.outcome === 'TARGET_HIT') groups[pat].wins++;
    else if (r.sim.outcome === 'SL_HIT') groups[pat].losses++;
    else groups[pat].inTrade++;
  }

  // Order: B first, then C, then new patterns
  const patternOrder = ['B', 'C', 'ENG', 'HAM', 'MAR', 'STAR', 'HAM2S', 'BW', 'SQZ', 'FLAG', 'TRI', 'DTRI', 'VCNB', 'OPEN_RCL'];
  const activeGroups = patternOrder.filter(p => groups[p]);

  return (
    <div className="summary-table-wrap">

      {/* ── Summary strip (totals) ──────────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: '2rem', padding: '0.75rem 1rem',
        borderBottom: '1px solid rgba(255,255,255,0.05)',
        fontSize: '0.75rem', fontFamily: 'var(--mono)',
        flexWrap: 'wrap',
      }}>
        <span><span style={{ color: 'var(--dim)' }}>Signals </span>
          <b style={{ color: 'white' }}>{signals.length}</b></span>
        <span><span style={{ color: 'var(--dim)' }}>Target hit </span>
          <b style={{ color: 'var(--green)' }}>{wins}</b></span>
        <span><span style={{ color: 'var(--dim)' }}>SL hit </span>
          <b style={{ color: 'var(--red)' }}>{losses}</b></span>
        <span><span style={{ color: 'var(--dim)' }}>In trade </span>
          <b style={{ color: 'var(--blue)' }}>{inTrade}</b></span>
        <span><span style={{ color: 'var(--dim)' }}>Win rate </span>
          <b style={{ color: wins > losses ? 'var(--green)' : 'var(--red)' }}>{winRate}%</b></span>
        <span style={{ marginLeft: 'auto' }}>
          <span style={{ color: 'var(--dim)' }}>Total P&L </span>
          <b style={{ color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)', fontSize: '0.85rem' }}>
            {totalPnl >= 0 ? '+' : ''}₹{Math.abs(totalPnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </b>
        </span>
      </div>

      {/* ── Per-pattern P&L breakdown ───────────────────────────────────────── */}
      {activeGroups.length > 1 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Math.min(activeGroups.length, 3)}, 1fr)`,
          gap: '1px',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          background: 'rgba(255,255,255,0.03)',
        }}>
          {activeGroups.map(pat => {
            const g   = groups[pat];
            const m   = PATTERN_META[pat] || { label: pat, color: 'var(--dim)' };
            const wr  = g.signals.length > 0 ? (g.wins / g.signals.length * 100).toFixed(0) : 0;
            const pnlUp = g.pnl >= 0;
            return (
              <div key={pat} style={{
                padding: '0.65rem 1rem',
                borderRight: '1px solid rgba(255,255,255,0.04)',
                fontFamily: 'var(--mono)',
              }}>
                {/* Pattern name */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.35rem' }}>
                  <span style={{
                    width: '8px', height: '8px', borderRadius: '50%',
                    background: m.color, flexShrink: 0,
                  }} />
                  <span style={{ fontSize: '0.7rem', fontWeight: 700, color: m.color }}>
                    {m.label}
                  </span>
                </div>
                {/* Stats row */}
                <div style={{ display: 'flex', gap: '0.6rem', fontSize: '0.65rem', flexWrap: 'wrap', marginBottom: '0.25rem' }}>
                  <span style={{ color: 'var(--dim)' }}>{g.signals.length} sig</span>
                  <span style={{ color: 'var(--green)' }}>{g.wins}T</span>
                  <span style={{ color: 'var(--red)' }}>{g.losses}SL</span>
                  <span style={{ color: 'var(--blue)' }}>{g.inTrade}I</span>
                  <span style={{ color: g.wins > g.losses ? 'var(--green)' : 'var(--red)' }}>
                    {wr}% WR
                  </span>
                </div>
                {/* P&L */}
                <div style={{
                  fontSize: '0.82rem', fontWeight: 700,
                  color: pnlUp ? 'var(--green)' : 'var(--red)',
                }}>
                  {pnlUp ? '+' : ''}₹{Math.abs(g.pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Detailed table ──────────────────────────────────────────────────── */}
      <div style={{ overflowX: 'auto' }}>
        <table className="summary-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Pattern</th>
              <th>Dip @ / Entry @</th>
              <th>Dip %</th>
              <th>Entry ₹</th>
              <th>SL ₹</th>
              <th>Target ₹</th>
              <th>Outcome</th>
              <th>LTP / Exit ₹</th>
              <th>P&L ₹</th>
              <th>P&L %</th>
            </tr>
          </thead>
          <tbody>
            {signals.map(r => {
              const sig    = r.entry_signal;
              const sim    = r.sim;
              const pnl    = livePnl(r);
              const pct    = livePnlPct(r);
              const exit   = liveExitPrice(r);
              const isLive = sim.outcome === 'IN_TRADE' && prices[r.instrument_key];
              const pnlUp  = pnl >= 0;

              return (
                <tr key={r.symbol}>
                  <td className="sym">{r.symbol}</td>
                  <td><PatternBadge pattern={sig.pattern} /></td>
                  <td style={{ fontFamily: 'var(--mono)', whiteSpace: 'nowrap' }}>
                    {sig.touch_time && sig.touch_time !== sig.entry_time
                      ? <><span style={{ color: 'var(--red)', opacity: 0.8 }}>{sig.touch_time}</span>
                          <span style={{ color: 'var(--dim)', margin: '0 3px' }}>→</span>
                          <span style={{ color: 'var(--green)' }}>{sig.entry_time}</span></>
                      : <span className="muted">{sig.entry_time}</span>}
                  </td>
                  <td style={{
                    fontFamily: 'var(--mono)',
                    color: sig.dip_pct != null ? (sig.dip_pct >= 0.3 ? 'var(--green)' : 'var(--gold)') : 'var(--dim)',
                  }}>
                    {sig.dip_pct != null
                      ? `${sig.dip_pct.toFixed(3)}%`
                      : sig.pattern === 'C'
                        ? `±${sig.atr}`
                        : '—'}
                  </td>
                  <td className="green">{fmt2(sig.entry)}</td>
                  <td className="red">{fmt2(sig.sl)}</td>
                  <td className="gold">{fmt2(sig.target)}</td>
                  <td><OutcomeBadge outcome={sim.outcome} /></td>
                  <td style={{ fontFamily: 'var(--mono)', color: isLive ? 'var(--blue)' : 'var(--dim)' }}>
                    {fmt2(exit)}{isLive && <span style={{ fontSize: '0.55rem', marginLeft: '4px', opacity: 0.7 }}>LIVE</span>}
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', color: pnlUp ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                    {pnlUp ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', color: pnlUp ? 'var(--green)' : 'var(--red)' }}>
                    {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
