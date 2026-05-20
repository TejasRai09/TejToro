export default function FilterPanel() {
  return (
    <div className="filter-panel">
      <div className="filter-inner">
        {/* Convergence filters */}
        <div>
          <div className="filter-group-title">
            <span style={{ color: 'var(--purple)' }}>◆</span>
            Convergence — cuts ~180 stocks to ~35
          </div>
          <div className="filter-item">
            <span className="fi-num">C1</span>
            <span>|[0] <b>Supertrend(6,2)</b> − [0] <b>VWAP</b>|</span>
            <span className="fi-op">&lt;</span>
            <span>[0] Close × <span className="fi-val">0.01</span></span>
            <span className="fi-desc">ST &amp; VWAP within 1%</span>
          </div>
          <div className="filter-item">
            <span className="fi-num">C2</span>
            <span>|[0] <b>VWAP</b> − <b>Daily PP</b>|</span>
            <span className="fi-op">&lt;</span>
            <span>[0] Close × <span className="fi-val">0.01</span></span>
            <span className="fi-desc">VWAP &amp; PP within 1%</span>
          </div>
        </div>

        {/* Price filters */}
        <div>
          <div className="filter-group-title">
            <span style={{ color: 'var(--blue)' }}>◆</span>
            Price filters — 3-candle strength
          </div>
          <div className="filter-item">
            <span className="fi-num">F1</span>
            <span>[0] Close</span>
            <span className="fi-op">≥</span>
            <span>[0] Supertrend(6,2)</span>
            <span className="fi-desc">above bullish ST</span>
          </div>
          <div className="filter-item">
            <span className="fi-num">F2</span>
            <span>[0] Close</span>
            <span className="fi-op">≥</span>
            <span>Daily Pivot Point</span>
            <span className="fi-desc">above PP</span>
          </div>
          <div className="filter-item">
            <span className="fi-num">F3</span>
            <span>[0] Close</span>
            <span className="fi-op">≥</span>
            <span>[0] VWAP</span>
            <span className="fi-desc">buyers in control</span>
          </div>
          <div className="filter-item">
            <span className="fi-num">F4</span>
            <span>[-1] Close</span>
            <span className="fi-op">≥</span>
            <span>[-1] VWAP</span>
            <span className="fi-desc">prev candle ✓</span>
          </div>
          <div className="filter-item">
            <span className="fi-num">F5</span>
            <span>[-2] Close</span>
            <span className="fi-op">≥</span>
            <span>[-2] VWAP</span>
            <span className="fi-desc">3-candle strength</span>
          </div>
          <div className="filter-item">
            <span className="fi-num">F6</span>
            <span>Market Cap</span>
            <span className="fi-op">≥</span>
            <span className="fi-val">₹1,000 Cr</span>
            <span className="fi-desc">large cap only</span>
          </div>
        </div>

        {/* Entry logic */}
        <div>
          <div className="filter-group-title">
            <span style={{ color: 'var(--green)' }}>◆</span>
            Entry pattern — VWAP touch
          </div>
          <div className="filter-item" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '0.3rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <span className="fi-num">E1</span>
              <span>[-1] candle low</span>
              <span className="fi-op">≤</span>
              <span>[-1] VWAP</span>
              <span className="fi-desc">stock tested VWAP</span>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <span className="fi-num">E2</span>
              <span>[0] close</span>
              <span className="fi-op">&gt;</span>
              <span>[-1] high</span>
              <span className="fi-desc">bullish breakout confirmed</span>
            </div>
          </div>
          <div className="filter-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
            <div style={{ fontSize: '0.64rem', color: 'var(--muted)', lineHeight: '1.7', fontFamily: 'var(--mono)' }}>
              <span style={{ color: 'var(--green)' }}>Entry</span> = [0] close &nbsp;·&nbsp;
              <span style={{ color: 'var(--red)' }}>SL</span> = [0] VWAP &nbsp;·&nbsp;
              <span style={{ color: 'var(--gold)' }}>Target</span> = entry + 3 × risk &nbsp;
              <span style={{ color: 'var(--dim)' }}>(1:3 R:R)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
