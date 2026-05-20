const fmt2 = (n) =>
  n != null ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';

const OUTCOME_META = {
  TARGET_HIT: { label: '🎯 TARGET HIT', color: 'var(--green)', bg: 'var(--green-10)' },
  SL_HIT:     { label: '🛑 SL HIT',     color: 'var(--red)',   bg: 'var(--red-10)'   },
  IN_TRADE:   { label: '📈 IN TRADE',   color: 'var(--blue)',  bg: 'var(--blue-10)'  },
};

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

export default function TestTable({ results }) {
  if (!results || results.length === 0) return null;

  const signals = results.filter(r => r.entry_signal && r.sim);

  const totalPnl  = signals.reduce((s, r) => s + r.sim.pnl, 0);
  const wins      = signals.filter(r => r.sim.outcome === 'TARGET_HIT').length;
  const losses    = signals.filter(r => r.sim.outcome === 'SL_HIT').length;
  const inTrade   = signals.filter(r => r.sim.outcome === 'IN_TRADE').length;
  const winRate   = signals.length > 0 ? (wins / signals.length * 100).toFixed(0) : 0;

  return (
    <div className="summary-table-wrap">
      {/* Summary strip */}
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

      <div style={{ overflowX: 'auto' }}>
        <table className="summary-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Pattern</th>
              <th>Signal @</th>
              <th>Dip %</th>
              <th>Entry ₹</th>
              <th>SL ₹</th>
              <th>Target ₹</th>
              <th>Outcome</th>
              <th>Exit @</th>
              <th>P&L ₹</th>
              <th>P&L %</th>
            </tr>
          </thead>
          <tbody>
            {signals.map(r => {
              const sig = r.entry_signal;
              const sim = r.sim;
              const pnlUp = sim.pnl >= 0;

              return (
                <tr key={r.symbol}>
                  <td className="sym">{r.symbol}</td>
                  <td>
                    <span style={{
                      fontSize: '0.62rem', fontWeight: 700, padding: '2px 8px', borderRadius: '999px',
                      background: sig.pattern === 'B' ? 'rgba(37,99,235,0.15)' : 'rgba(124,58,237,0.15)',
                      color: sig.pattern === 'B' ? '#60a5fa' : '#a78bfa',
                      fontFamily: 'var(--mono)',
                    }}>
                      {sig.pattern === 'B' ? 'VWAP Reclaim' : 'Breakout Retest'}
                    </span>
                  </td>
                  <td className="muted" style={{ fontFamily: 'var(--mono)' }}>{sig.entry_time}</td>
                  <td style={{
                    fontFamily: 'var(--mono)',
                    color: sig.dip_pct != null ? (sig.dip_pct >= 0.3 ? 'var(--green)' : 'var(--gold)') : 'var(--dim)',
                  }}>
                    {sig.dip_pct != null ? `${sig.dip_pct.toFixed(3)}%` : sig.pattern === 'C' ? `±${sig.atr}` : '—'}
                  </td>
                  <td className="green">{fmt2(sig.entry)}</td>
                  <td className="red">{fmt2(sig.sl)}</td>
                  <td className="gold">{fmt2(sig.target)}</td>
                  <td><OutcomeBadge outcome={sim.outcome} /></td>
                  <td className="muted" style={{ fontFamily: 'var(--mono)' }}>{sim.exit_time}</td>
                  <td style={{ fontFamily: 'var(--mono)', color: pnlUp ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                    {pnlUp ? '+' : ''}₹{Math.abs(sim.pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </td>
                  <td style={{ fontFamily: 'var(--mono)', color: pnlUp ? 'var(--green)' : 'var(--red)' }}>
                    {sim.pnl_pct >= 0 ? '+' : ''}{sim.pnl_pct.toFixed(2)}%
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
