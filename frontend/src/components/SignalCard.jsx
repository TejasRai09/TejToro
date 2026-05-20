import CandleChart from './CandleChart.jsx';

const TRADE_CAPITAL = 200_000;

const PATTERN_META = {
  B: { label: 'Pattern B', desc: 'VWAP Reclaim',    color: '#2563eb', bg: 'rgba(37,99,235,0.12)'  },
  C: { label: 'Pattern C', desc: 'Breakout Retest', color: '#7c3aed', bg: 'rgba(124,58,237,0.12)' },
};

function PatternBadge({ pattern }) {
  const m = PATTERN_META[pattern];
  if (!m) return null;
  return (
    <span style={{
      fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.06em',
      padding: '2px 8px', borderRadius: '999px',
      background: m.bg, color: m.color,
      border: `1px solid ${m.color}40`,
      fontFamily: 'var(--mono)', marginLeft: '0.5rem',
      verticalAlign: 'middle',
    }}>
      {m.label}
    </span>
  );
}

function patternDesc(sig) {
  const m = PATTERN_META[sig?.pattern];
  return m ? m.desc : 'VWAP touch';
}

// ── Confidence ring SVG ───────────────────────────────────────────────────────
function ConfRing({ conf }) {
  const R   = 24;
  const C   = 2 * Math.PI * R;
  const pct = Math.min(100, Math.max(0, conf));
  const color =
    pct >= 70 ? '#00ff9f' :
    pct >= 50 ? '#ffb800' : '#ff3b5c';

  return (
    <div className="conf-ring-wrap" title={`Confidence: ${conf}/100`}>
      <svg width="62" height="62">
        <circle
          cx="31" cy="31" r={R}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="3"
          style={{ transform: 'rotate(-90deg)', transformOrigin: '31px 31px' }}
        />
        <circle
          cx="31" cy="31" r={R}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${C * pct / 100} ${C * (1 - pct / 100)}`}
          style={{
            transform: 'rotate(-90deg)',
            transformOrigin: '31px 31px',
            transition: 'stroke-dasharray 0.6s ease',
            filter: `drop-shadow(0 0 4px ${color}60)`,
          }}
        />
      </svg>
      <div className="conf-ring-text">
        <div className="conf-num" style={{ color }}>{conf}</div>
        <div className="conf-label">/100</div>
      </div>
    </div>
  );
}

// ── Trade cell ────────────────────────────────────────────────────────────────
function TradeCell({ label, price, sub, colorClass }) {
  return (
    <div className="trade-cell">
      <div className="tc-label">{label}</div>
      <div className={`tc-price ${colorClass}`}>₹{price.toLocaleString('en-IN')}</div>
      <div className="tc-sub">{sub}</div>
    </div>
  );
}

// ── Live price section ────────────────────────────────────────────────────────
function LiveSection({ sig, ltp, marketOpen }) {
  if (!marketOpen) {
    const shares   = sig.entry > 0 ? Math.floor(TRADE_CAPITAL / sig.entry) : 0;
    const invested = (shares * sig.entry).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    const maxLoss  = (shares * sig.risk).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    const maxGain  = (shares * sig.reward).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    return (
      <div className="live-section">
        <div style={{ fontSize: '0.62rem', color: 'var(--dim)', fontFamily: 'var(--mono)', marginBottom: '0.6rem' }}>
          Market closed — projected values
        </div>
        <div className="pnl-grid">
          <div className="pnl-cell">
            <div className="pnl-label">Shares (₹2L)</div>
            <div className="pnl-val">{shares}</div>
            <div className="pnl-sub">₹{invested}</div>
          </div>
          <div className="pnl-cell">
            <div className="pnl-label">Max Loss</div>
            <div className="pnl-val red">-₹{maxLoss}</div>
            <div className="pnl-sub">if SL hit</div>
          </div>
          <div className="pnl-cell">
            <div className="pnl-label">Max Gain</div>
            <div className="pnl-val green">+₹{maxGain}</div>
            <div className="pnl-sub">if target hit</div>
          </div>
          <div className="pnl-cell">
            <div className="pnl-label">R:R Ratio</div>
            <div className="pnl-val" style={{ color: 'var(--gold)' }}>1 : 3</div>
            <div className="pnl-sub">fixed</div>
          </div>
        </div>
      </div>
    );
  }

  if (ltp === null) {
    return (
      <div className="live-section" style={{ padding: '0.8rem 1.1rem' }}>
        <div style={{ fontSize: '0.64rem', color: 'var(--dim)', fontFamily: 'var(--mono)' }}>
          ⏳ Fetching live price…
        </div>
      </div>
    );
  }

  const shares   = sig.entry > 0 ? Math.floor(TRADE_CAPITAL / sig.entry) : 0;
  const invested = shares * sig.entry;
  const pnl      = shares * (ltp - sig.entry);
  const pnlPct   = ((ltp - sig.entry) / sig.entry * 100);
  const maxLoss  = shares * sig.risk;
  const maxGain  = shares * sig.reward;

  const ltpDiff  = ltp - sig.entry;
  const priceUp  = ltpDiff >= 0;
  const priceColor = priceUp ? 'var(--green)' : 'var(--red)';

  const rng  = sig.target - sig.sl;
  const prog = rng > 0 ? Math.min(100, Math.max(0, (ltp - sig.sl) / rng * 100)) : 0;
  const progColor =
    prog >= 66 ? 'var(--green)' :
    prog >= 33 ? 'var(--gold)'  : 'var(--red)';

  const isTarget = ltp >= sig.target;
  const isSL     = ltp <= sig.sl;
  const statusText  = isTarget ? '🎯 TARGET HIT' : isSL ? '🛑 SL HIT' : '📈 IN TRADE';
  const statusBg    = isTarget ? 'var(--green-10)' : isSL ? 'var(--red-10)' : 'var(--blue-10)';
  const statusBorder = isTarget ? 'rgba(0,255,159,0.25)' : isSL ? 'rgba(255,59,92,0.25)' : 'rgba(77,159,255,0.25)';
  const statusColor  = isTarget ? 'var(--green)' : isSL ? 'var(--red)' : 'var(--blue)';

  const fmt = (n, dec = 2) => Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const fmtI = (n) => Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });

  return (
    <div className="live-section">
      <div className="live-row">
        <div>
          <div className="live-label">Live Price · 5s refresh</div>
          <div className="live-price-val" style={{ color: priceColor }}>
            ₹{ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="live-change" style={{ color: priceColor }}>
            {priceUp ? '+' : '-'}₹{fmt(ltpDiff)} &nbsp;({priceUp ? '+' : '-'}{fmt(Math.abs(pnlPct))}%)
          </div>
        </div>
        <div className="trade-status">
          <div className="live-label" style={{ textAlign: 'right' }}>Status</div>
          <div
            className="status-badge-pill"
            style={{ background: statusBg, border: `1px solid ${statusBorder}`, color: statusColor, marginTop: '0.3rem' }}
          >
            {statusText}
          </div>
        </div>
      </div>

      {/* Progress */}
      <div className="trade-progress">
        <div className="trade-progress-labels">
          <span>🛑 ₹{sig.sl}</span>
          <span>Entry ₹{sig.entry}</span>
          <span>🎯 ₹{sig.target}</span>
        </div>
        <div className="trade-progress-track">
          <div
            className="trade-progress-fill"
            style={{ width: `${prog}%`, background: progColor, boxShadow: `0 0 6px ${progColor}60` }}
          />
        </div>
      </div>

      {/* P&L grid */}
      <div className="pnl-grid">
        <div className="pnl-cell">
          <div className="pnl-label">Shares (₹2L)</div>
          <div className="pnl-val">{shares}</div>
          <div className="pnl-sub">₹{fmtI(invested)}</div>
        </div>
        <div className="pnl-cell">
          <div className="pnl-label">Live P&amp;L</div>
          <div className="pnl-val" style={{ color: pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {pnl >= 0 ? '+' : '-'}₹{fmtI(pnl)}
          </div>
          <div className="pnl-sub" style={{ color: pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {pnlPct >= 0 ? '+' : ''}{fmt(pnlPct)}%
          </div>
        </div>
        <div className="pnl-cell">
          <div className="pnl-label">Max Loss</div>
          <div className="pnl-val red">-₹{fmtI(maxLoss)}</div>
          <div className="pnl-sub">if SL hit</div>
        </div>
        <div className="pnl-cell">
          <div className="pnl-label">Max Gain</div>
          <div className="pnl-val green">+₹{fmtI(maxGain)}</div>
          <div className="pnl-sub">if target</div>
        </div>
      </div>
    </div>
  );
}

// ── Signal Card ───────────────────────────────────────────────────────────────
export default function SignalCard({ result, ltp, marketOpen, isLate }) {
  const sig  = result.entry_signal;
  const conf = result.confidence;
  const ikey = result.instrument_key;

  if (!sig) return null;

  return (
    <div className="signal-card" style={isLate ? { borderColor: 'rgba(234,179,8,0.4)', opacity: 0.9 } : {}}>
      {/* Header */}
      <div className="signal-header">
        <div>
          <div className="signal-sym">
            <span className="signal-sym-icon">⚡</span>
            {result.symbol}
            <PatternBadge pattern={sig.pattern} />
            {isLate && (
              <span style={{
                fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.06em',
                padding: '2px 7px', borderRadius: '999px',
                background: 'rgba(234,179,8,0.12)', color: '#92400e',
                border: '1px solid rgba(234,179,8,0.4)',
                fontFamily: 'var(--mono)', marginLeft: '0.4rem',
                verticalAlign: 'middle',
              }}>LATE</span>
            )}
          </div>
          <div className="signal-meta">
            {patternDesc(sig)} @ {sig.touch_time} → entry @ {sig.entry_time}
            &nbsp;·&nbsp;MCap ₹{result.mcap.toLocaleString('en-IN')} Cr
            &nbsp;·&nbsp;ST-VWAP {result.st_vwap_gap_pct}%
            &nbsp;·&nbsp;VWAP-PP {result.vwap_pp_gap_pct}%
            {sig.candles_below && <>&nbsp;·&nbsp;{sig.candles_below} candle{sig.candles_below > 1 ? 's' : ''} below VWAP</>}
            {sig.retest_candles && <>&nbsp;·&nbsp;{sig.retest_candles} candle retest · ATR ₹{sig.atr}</>}
          </div>
        </div>
        <ConfRing conf={conf} />
      </div>

      {/* Trade levels */}
      <div className="trade-grid">
        <TradeCell
          label="BUY Entry"
          price={sig.entry}
          sub={`${sig.entry_time} candle close`}
          colorClass="green"
        />
        <TradeCell
          label="Stop Loss"
          price={sig.sl}
          sub={`VWAP · -₹${sig.risk.toFixed(2)}/sh`}
          colorClass="red"
        />
        <TradeCell
          label="Target 1:3"
          price={sig.target}
          sub={`+₹${sig.reward.toFixed(2)}/share`}
          colorClass="gold"
        />
        <TradeCell
          label={`VWAP Touch @ ${sig.touch_time}`}
          price={sig.touch_vwap}
          sub={`L ₹${sig.touch_low} ≤ VWAP ✓`}
          colorClass="blue"
        />
      </div>

      {/* Live section */}
      <LiveSection sig={sig} ltp={ltp} marketOpen={marketOpen} />

      {/* Live chart */}
      {ikey && (
        <div className="chart-wrap">
          <div className="chart-label">
            10-min candles · today
            <div className="chart-legend">
              <div className="chart-legend-item">
                <div className="chart-legend-line" style={{ background: '#059669' }} />
                <span style={{ color: '#059669' }}>Bullish</span>
              </div>
              <div className="chart-legend-item">
                <div className="chart-legend-line" style={{ background: '#dc2626' }} />
                <span style={{ color: '#dc2626' }}>Bearish</span>
              </div>
              <div className="chart-legend-item">
                <div className="chart-legend-line" style={{ background: '#7c3aed' }} />
                <span style={{ color: '#7c3aed' }}>VWAP</span>
              </div>
            </div>
          </div>
          <CandleChart instrumentKey={ikey} sig={sig} ltp={ltp} />
        </div>
      )}
    </div>
  );
}
