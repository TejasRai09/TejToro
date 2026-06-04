import CandleChart from './CandleChart.jsx';

const TRADE_CAPITAL = 200_000;

const PATTERN_META = {
  B:     { label: 'VWAP Reclaim',      color: '#60a5fa', bg: 'rgba(37,99,235,0.15)'   },
  C:     { label: 'Breakout Retest',   color: '#a78bfa', bg: 'rgba(124,58,237,0.15)'  },
  ENG:   { label: 'Bullish Engulfing', color: '#34d399', bg: 'rgba(5,150,105,0.15)'   },
  HAM:   { label: 'Hammer / Pin Bar',  color: '#fbbf24', bg: 'rgba(217,119,6,0.15)'   },
  MAR:   { label: 'Marubozu Reclaim',  color: '#f472b6', bg: 'rgba(219,39,119,0.15)'  },
  STAR:  { label: 'Morning Star',      color: '#fb923c', bg: 'rgba(234,88,12,0.15)'   },
  HAM2S: { label: 'Hammer −2σ Band',   color: '#fcd34d', bg: 'rgba(252,211,77,0.15)'  },
  BW:    { label: 'Band Walk +1σ',     color: '#4ade80', bg: 'rgba(74,222,128,0.15)'  },
  SQZ:   { label: 'Squeeze Breakout',  color: '#c084fc', bg: 'rgba(192,132,252,0.15)' },
  FLAG:     { label: 'Bull Flag',        color: '#f59e0b', bg: 'rgba(245,158,11,0.15)'  },
  TRI:      { label: 'Asc Triangle',    color: '#06b6d4', bg: 'rgba(6,182,212,0.15)'   },
  DTRI:     { label: 'Desc Triangle',   color: '#f97316', bg: 'rgba(249,115,22,0.15)'  },
  VCNB:     { label: 'VWAP Consol BRK', color: '#10b981', bg: 'rgba(16,185,129,0.15)' },
  OPEN_RCL: { label: 'Opening Reclaim', color: '#e879f9', bg: 'rgba(232,121,249,0.15)' },
};

// Pattern-specific meta line below the symbol
const SIGNAL_META = {
  B:     (sig) => `Dip from VWAP @ ${sig.touch_time} → entry @ ${sig.entry_time}`,
  C:     (sig) => `Initial break @ ${sig.touch_time} → retest → entry @ ${sig.entry_time}`,
  ENG:   (sig) => `Red dip @ ${sig.touch_time} → engulfing entry @ ${sig.entry_time}`,
  HAM:   (sig) => `Hammer formed @ ${sig.touch_time}`,
  MAR:   (sig) => `Marubozu reclaim → entry @ ${sig.entry_time}`,
  STAR:  (sig) => `Morning star @ ${sig.touch_time} → entry @ ${sig.entry_time}`,
  HAM2S: (sig) => `Hammer at −2σ band @ ${sig.touch_time} · range day mean reversion`,
  BW:    (sig) => `Band walk pullback to +1σ @ ${sig.touch_time} · trend continuation`,
  SQZ:   (sig) => `Squeeze breakout above +1σ @ ${sig.entry_time}`,
  FLAG:     (sig) => `Bull flag breakout @ ${sig.entry_time}${sig.pole_pct ? ` · pole ${sig.pole_pct}%` : ''}`,
  TRI:      (sig) => `Ascending triangle breakout @ ${sig.entry_time}${sig.touches ? ` · ${sig.touches} touches` : ''}`,
  DTRI:     (sig) => `Descending triangle breakout @ ${sig.entry_time}${sig.touches ? ` · ${sig.touches} touches` : ''}`,
  VCNB:     (sig) => `VWAP consolidation breakout @ ${sig.entry_time}${sig.consol_pct ? ` · base ${sig.consol_pct}%` : ''}`,
  OPEN_RCL: (sig) => `Weak open → VWAP reclaim @ ${sig.entry_time} · dip ${sig.dip_pct}%`,
};

// Pattern-specific label + sub for the 4th trade card
const TOUCH_LABEL = {
  B:     (sig) => `Dip Started @ ${sig.touch_time}`,
  C:     (sig) => `Initial Break @ ${sig.touch_time}`,
  ENG:   (sig) => `Red Candle @ ${sig.touch_time}`,
  HAM:   (sig) => `Hammer @ ${sig.touch_time}`,
  MAR:   (sig) => `Pre-Candle @ ${sig.touch_time}`,
  STAR:  (sig) => `Red Candle @ ${sig.touch_time}`,
  HAM2S: (sig) => `−2σ Band @ ${sig.touch_time}`,
  BW:    (sig) => `+1σ Touch @ ${sig.touch_time}`,
  SQZ:   (sig) => `Squeeze Break @ ${sig.entry_time}`,
  FLAG:     (sig) => `Flag High ₹${sig.touch_high}`,
  TRI:      (sig) => `Resistance ₹${sig.touch_high}`,
  DTRI:     (sig) => `Support ₹${sig.touch_low}`,
  VCNB:     (sig) => `VWAP @ ${sig.touch_time}`,
  OPEN_RCL: (sig) => `Open Low ₹${sig.touch_low}`,
};
const TOUCH_SUB = {
  B:     (sig) => `L ₹${sig.touch_low} ≤ VWAP ✓`,
  C:     (sig) => `Retest zone ±₹${sig.atr || '—'}`,
  ENG:   (sig) => `L ₹${sig.touch_low} ≤ VWAP ✓`,
  HAM:   (sig) => `Wick ₹${sig.touch_low} ≤ VWAP ✓`,
  MAR:   (sig) => `Prev candle below VWAP ✓`,
  STAR:  (sig) => `Closed near VWAP ✓`,
  HAM2S: (sig) => `Wick ₹${sig.touch_low} ≤ −2σ ✓`,
  BW:    (sig) => `Band ₹${sig.touch_vwap} held ✓`,
  SQZ:   (sig) => `Close above +1σ ✓`,
  FLAG:     (sig) => `Breakout above flag ✓`,
  TRI:      (sig) => `Breakout above resistance ✓`,
  DTRI:     (sig) => `Breakout above descending line ✓`,
  VCNB:     (sig) => `Close > VWAP + 5-bar high ✓`,
  OPEN_RCL: (sig) => `Reclaim above VWAP ✓`,
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

// ── Confidence ring ───────────────────────────────────────────────────────────
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
function LiveSection({ sig, ltp, marketOpen, sim }) {
  const fmtI = (n) => Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  const fmt2 = (n) => Number(Math.abs(n)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  if (!marketOpen) {
    const shares   = sig.entry > 0 ? Math.floor(TRADE_CAPITAL / sig.entry) : 0;
    const maxLoss  = fmtI(shares * sig.risk);
    const maxGain  = fmtI(shares * sig.reward);

    // ── Test mode: sim data available — show actual outcome ──────────────────
    if (sim) {
      const { outcome, exit_price, pnl, pnl_pct } = sim;
      const simShares = sim.shares ?? shares;
      const pnlUp     = pnl >= 0;

      const OUTCOME = {
        TARGET_HIT: { text: '🎯 TARGET HIT', color: 'var(--green)', bg: 'var(--green-10)', border: 'rgba(0,255,159,0.25)' },
        SL_HIT:     { text: '🛑 SL HIT',     color: 'var(--red)',   bg: 'var(--red-10)',   border: 'rgba(255,59,92,0.25)'  },
        IN_TRADE:   { text: '📈 IN TRADE',   color: 'var(--blue)',  bg: 'var(--blue-10)',  border: 'rgba(77,159,255,0.25)' },
      };
      const o = OUTCOME[outcome] || OUTCOME.IN_TRADE;

      return (
        <div className="live-section">
          <div className="live-row">
            <div>
              <div className="live-label">Exit Price</div>
              <div className="live-price-val" style={{ color: 'var(--text2)', fontSize: '1.3rem' }}>
                ₹{exit_price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>
            <div className="trade-status">
              <div className="live-label" style={{ textAlign: 'right' }}>Outcome</div>
              <div className="status-badge-pill" style={{
                background: o.bg, border: `1px solid ${o.border}`,
                color: o.color, marginTop: '0.3rem',
              }}>
                {o.text}
              </div>
            </div>
          </div>

          <div className="pnl-grid">
            <div className="pnl-cell">
              <div className="pnl-label">Shares (₹2L)</div>
              <div className="pnl-val">{simShares}</div>
              <div className="pnl-sub">₹{fmtI(simShares * sig.entry)}</div>
            </div>
            <div className="pnl-cell">
              <div className="pnl-label">Actual P&amp;L</div>
              <div className="pnl-val" style={{ color: pnlUp ? 'var(--green)' : 'var(--red)', fontSize: '1.1rem' }}>
                {pnlUp ? '+' : '−'}₹{fmtI(pnl)}
              </div>
              <div className="pnl-sub" style={{ color: pnlUp ? 'var(--green)' : 'var(--red)' }}>
                {pnl_pct >= 0 ? '+' : ''}{fmt2(pnl_pct)}%
              </div>
            </div>
            <div className="pnl-cell">
              <div className="pnl-label">Max Loss</div>
              <div className="pnl-val red">-₹{maxLoss}</div>
              <div className="pnl-sub">if SL hit</div>
            </div>
            <div className="pnl-cell">
              <div className="pnl-label">Max Gain</div>
              <div className="pnl-val green">+₹{maxGain}</div>
              <div className="pnl-sub">if target</div>
            </div>
          </div>
        </div>
      );
    }

    // ── Production mode: no sim — show projected values only ─────────────────
    return (
      <div className="live-section">
        <div style={{ fontSize: '0.62rem', color: 'var(--dim)', fontFamily: 'var(--mono)', marginBottom: '0.6rem' }}>
          Market closed — projected values
        </div>
        <div className="pnl-grid">
          <div className="pnl-cell">
            <div className="pnl-label">Shares (₹2L)</div>
            <div className="pnl-val">{shares}</div>
            <div className="pnl-sub">₹{fmtI(shares * sig.entry)}</div>
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
            {(SIGNAL_META[sig.pattern] || ((s) => `Signal @ ${s.touch_time} → entry @ ${s.entry_time}`))(sig)}
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
          label={(TOUCH_LABEL[sig.pattern] || ((s) => `Ref @ ${s.touch_time}`))(sig)}
          price={sig.touch_vwap}
          sub={(TOUCH_SUB[sig.pattern] || ((s) => `L ₹${s.touch_low}`))(sig)}
          colorClass="blue"
        />
      </div>

      {/* Live section */}
      <LiveSection sig={sig} ltp={ltp} marketOpen={marketOpen} sim={result.sim} />

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
