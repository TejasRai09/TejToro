import { useState } from 'react';

const fmt2 = (n) => n?.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—';
const fmtI = (n) => n?.toLocaleString('en-IN', { maximumFractionDigits: 0 }) ?? '—';

const COLS = [
  { key: 'signal',          label: 'Signal',       sortKey: r => r.entry_signal ? 1 : 0 },
  { key: 'confidence',      label: 'Conf',         sortKey: r => r.confidence },
  { key: 'symbol',          label: 'Symbol',       sortKey: r => r.symbol },
  { key: 'live_price',      label: 'Live ₹',       sortKey: r => r._ltp ?? 0 },
  { key: 'delta',           label: 'Δ Close',      sortKey: r => r._delta ?? 0 },
  { key: 'mcap',            label: 'MCap (Cr)',    sortKey: r => r.mcap },
  { key: 'c0_time',         label: '[0] Time',     sortKey: r => r.c0_time },
  { key: 'c0_close',        label: '[0] Close',    sortKey: r => r.c0_close },
  { key: 'c0_vwap',         label: '[0] VWAP',     sortKey: r => r.c0_vwap },
  { key: 'c0_st',           label: '[0] ST',       sortKey: r => r.c0_st },
  { key: 'pp',              label: 'Pivot PP',     sortKey: r => r.pp },
  { key: 'st_vwap_gap_pct', label: '|ST-VWAP|%',  sortKey: r => r.st_vwap_gap_pct },
  { key: 'vwap_pp_gap_pct', label: '|VWAP-PP|%',  sortKey: r => r.vwap_pp_gap_pct },
  { key: 'entry',           label: 'Entry',        sortKey: r => r.entry_signal?.entry ?? 0 },
  { key: 'sl',              label: 'SL',           sortKey: r => r.entry_signal?.sl ?? 0 },
  { key: 'target',          label: 'Target',       sortKey: r => r.entry_signal?.target ?? 0 },
];

export default function SummaryTable({ results, prices, marketOpen }) {
  const [sortCol, setSortCol] = useState('confidence');
  const [sortAsc, setSortAsc] = useState(false);

  const handleSort = (key) => {
    if (sortCol === key) setSortAsc(a => !a);
    else { setSortCol(key); setSortAsc(false); }
  };

  const enriched = results.map(r => {
    const ltp    = prices[r.instrument_key] ?? null;
    const delta  = ltp !== null ? parseFloat((ltp - r.c0_close).toFixed(2)) : null;
    return { ...r, _ltp: ltp, _delta: delta };
  });

  const col     = COLS.find(c => c.key === sortCol);
  const sorted  = col
    ? [...enriched].sort((a, b) => {
        const va = col.sortKey(a);
        const vb = col.sortKey(b);
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ?  1 : -1;
        return 0;
      })
    : enriched;

  return (
    <div className="summary-table-wrap">
      <div style={{ overflowX: 'auto' }}>
        <table className="summary-table">
          <thead>
            <tr>
              {COLS.map(c => (
                <th key={c.key} onClick={() => handleSort(c.key)}>
                  {c.label}
                  {sortCol === c.key && (
                    <span style={{ marginLeft: '0.3rem', opacity: 0.5 }}>
                      {sortAsc ? '▲' : '▼'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const sig   = r.entry_signal;
              const ltp   = r._ltp;
              const delta = r._delta;
              const deltaUp = delta !== null ? delta >= 0 : null;

              let ltpDisplay = '—';
              let ltpClass   = 'muted';
              if (!marketOpen) { ltpDisplay = 'Closed'; ltpClass = 'muted'; }
              else if (ltp !== null) {
                ltpDisplay = `₹${fmt2(ltp)}`;
                ltpClass   = delta >= 0 ? 'green' : 'red';
              }

              return (
                <tr key={r.symbol}>
                  <td>
                    {sig ? (
                      <span className="sig-chip buy">⚡ BUY</span>
                    ) : (
                      <span className="sig-chip watch">👁 Watch</span>
                    )}
                  </td>
                  <td className={sig ? (r.confidence >= 70 ? 'green' : r.confidence >= 50 ? 'gold' : 'red') : 'muted'}>
                    {sig ? `${r.confidence}/100` : '—'}
                  </td>
                  <td className="sym">{r.symbol}</td>
                  <td className={ltpClass}>{ltpDisplay}</td>
                  <td className={deltaUp === null ? 'muted' : deltaUp ? 'green' : 'red'}>
                    {delta !== null ? `${delta >= 0 ? '+' : ''}${fmt2(delta)}` : '—'}
                  </td>
                  <td className="muted">₹{fmtI(r.mcap)}</td>
                  <td className="muted">{r.c0_time}</td>
                  <td className="muted">{fmt2(r.c0_close)}</td>
                  <td className="blue">{fmt2(r.c0_vwap)}</td>
                  <td className="purple">{fmt2(r.c0_st)}</td>
                  <td className="muted">{fmt2(r.pp)}</td>
                  <td className={r.st_vwap_gap_pct < 0.5 ? 'green' : 'muted'}>
                    {r.st_vwap_gap_pct}%
                  </td>
                  <td className={r.vwap_pp_gap_pct < 0.5 ? 'green' : 'muted'}>
                    {r.vwap_pp_gap_pct}%
                  </td>
                  <td className={sig ? 'green' : 'muted'}>{sig ? `₹${fmt2(sig.entry)}` : '—'}</td>
                  <td className={sig ? 'red'   : 'muted'}>{sig ? `₹${fmt2(sig.sl)}`    : '—'}</td>
                  <td className={sig ? 'gold'  : 'muted'}>{sig ? `₹${fmt2(sig.target)}`: '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
