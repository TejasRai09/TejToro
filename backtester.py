"""
backtester.py - Backtest the Open Drive Pivot strategy on historical daily data.

This replays the EXACT same logic as scanner.py on historical data:
    - Pivot points from previous day's OHLC
    - Open = Low check (Open Drive signal)
    - RSI > WMA RSI momentum filter
    - R:R ratio and R1 distance checks
    - Position sizing with your capital constraints
    - Exit simulation: T1 (R1), T2 (R2), Stop (PP), Time Exit (Close)

How the daily data maps to your intraday rules:
    Live System                     Daily Backtest
    ----------------------------    ----------------------------
    First candle Open = Low         Daily Open = Low (within tolerance)
    Entry = current LTP             Entry = Open price
    Stop = VWAP at signal time      Stop = PP (pivot - institutional support)
    Price > VWAP                    Open > PP (same concept)
    Price > PP                      Open > PP
    R1, R2 from prev day pivots     Same - exact calculation
    RSI(14) on 10-min candles       RSI(14) on daily closes
    WMA(21) of RSI                  Same calculation on daily RSI
    Exit at T1/T2/Stop/Close        High/Low/Close of the day

Run:  python backtester.py
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from config import (
    MIN_STOCK_PRICE, MAX_STOCK_PRICE,
    MIN_RR_RATIO, MIN_R1_DISTANCE_PCT, OPEN_LOW_TOLERANCE,
    MAX_RISK_PER_TRADE, MAX_TRADE_VALUE,
    T1_EXIT_PCT, T2_EXIT_PCT,
    DAILY_LOSS_LIMIT, MAX_TRADES_PER_DAY, MAX_SIMULTANEOUS,
    TOTAL_CAPITAL, RSI_PERIOD, WMA_PERIOD,
)

DATA_DIR    = "backtest_data"
RESULTS_DIR = "backtest_results"

# ── Indicator Calculations (same as indicators.py) ────────────────────────

def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """RSI using Wilder's smoothing - identical to indicators.py"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_wma(series: pd.Series, period: int = WMA_PERIOD) -> pd.Series:
    """Weighted Moving Average - identical to indicators.py"""
    weights = np.arange(1, period + 1, dtype=float)
    def _wma(window):
        if len(window) < period:
            return np.nan
        return np.dot(window, weights) / weights.sum()
    return series.rolling(window=period).apply(_wma, raw=True)


def calc_pivots(prev_high, prev_low, prev_close):
    """Standard pivot points from previous day"""
    PP = (prev_high + prev_low + prev_close) / 3
    R1 = (2 * PP) - prev_low
    R2 = PP + (prev_high - prev_low)
    S1 = (2 * PP) - prev_high
    S2 = PP - (prev_high - prev_low)
    return round(PP,2), round(R1,2), round(R2,2), round(S1,2), round(S2,2)


# ── Load Data ─────────────────────────────────────────────────────────────

def load_all_data() -> dict:
    """Load all daily CSV files from backtest_data/"""
    data = {}
    if not os.path.exists(DATA_DIR):
        print(f"ERROR: {DATA_DIR}/ not found. Run collect_data.py first.")
        return data

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]
    for f in files:
        symbol = f.replace(".csv", "")
        try:
            df = pd.read_csv(
                os.path.join(DATA_DIR, f),
                index_col=0, parse_dates=True
            )
            df = df.sort_index()
            # Need at least RSI_PERIOD + WMA_PERIOD + 2 days for warmup
            if len(df) >= (RSI_PERIOD + WMA_PERIOD + 5):
                data[symbol] = df
        except Exception:
            continue
    return data


# ── Core Backtest Engine ──────────────────────────────────────────────────

def run_backtest():
    print("=" * 60)
    print("  OPEN DRIVE PIVOT STRATEGY - BACKTEST")
    print("=" * 60)

    # Load data
    print("\nLoading historical data...")
    all_data = load_all_data()
    print(f"  Loaded {len(all_data)} stocks with sufficient data")

    if not all_data:
        print("No data found. Run collect_data.py first.")
        return

    # Pre-compute RSI and WMA for all stocks
    print("Computing indicators (RSI, WMA RSI)...")
    stock_indicators = {}
    for symbol, df in all_data.items():
        rsi = calc_rsi(df["close"], RSI_PERIOD)
        wma_rsi = calc_wma(rsi, WMA_PERIOD)
        stock_indicators[symbol] = {
            "rsi": rsi,
            "wma_rsi": wma_rsi,
        }

    # Get all unique trading dates across all stocks
    all_dates = set()
    for df in all_data.values():
        all_dates.update(df.index.date)
    all_dates = sorted(all_dates)

    # Skip first 40 days for indicator warmup
    warmup = RSI_PERIOD + WMA_PERIOD + 5
    trade_dates = all_dates[warmup:]

    print(f"  Trading period: {trade_dates[0]} to {trade_dates[-1]}")
    print(f"  Trading days: {len(trade_dates)}")
    print(f"\nRunning backtest with your exact rules...")
    print(f"  Capital: Rs.{TOTAL_CAPITAL:,}")
    print(f"  Max risk/trade: Rs.{MAX_RISK_PER_TRADE:,}")
    print(f"  Max trades/day: {MAX_TRADES_PER_DAY}")
    print(f"  Max simultaneous: {MAX_SIMULTANEOUS}")
    print(f"  Daily loss limit: Rs.{DAILY_LOSS_LIMIT:,}")
    print(f"  Open=Low tolerance: {OPEN_LOW_TOLERANCE*100:.2f}%")
    print(f"  Min R:R ratio: {MIN_RR_RATIO}")
    print(f"  Min R1 distance: {MIN_R1_DISTANCE_PCT}%")

    # ── Results tracking ──────────────────────────────────────────────────
    all_trades = []
    equity_curve = [{"date": str(trade_dates[0]), "equity": TOTAL_CAPITAL}]
    running_capital = TOTAL_CAPITAL
    total_signals_checked = 0

    # Daily stats
    daily_stats = []

    for day_idx, today in enumerate(trade_dates):
        day_trades_taken = 0
        day_loss = 0.0
        day_gain = 0.0
        day_signals = 0
        day_halted = False
        start_of_day_capital = running_capital
        daily_capital_used = 0.0

        # Scan every stock for today
        for symbol, df in all_data.items():
            if day_halted:
                break
            if day_trades_taken >= MAX_TRADES_PER_DAY:
                break

            # Check if this stock has data for today AND yesterday
            if today not in df.index.date:
                continue

            today_mask = df.index.date == today
            today_rows = df[today_mask]
            if today_rows.empty:
                continue

            # Get previous trading day for this stock
            prev_mask = df.index.date < today
            prev_rows = df[prev_mask]
            if prev_rows.empty:
                continue

            prev_day_date = prev_rows.index[-1].date()
            prev_day_mask = df.index.date == prev_day_date
            prev_day_rows = df[prev_day_mask]

            today_candle = today_rows.iloc[0]  # daily bar
            prev_candle = prev_day_rows.iloc[-1]

            total_signals_checked += 1

            # ══════════════════════════════════════════════════════════════
            #  APPLY THE 9 RULES (same order as scanner.py)
            # ══════════════════════════════════════════════════════════════

            open_price  = today_candle["open"]
            high_price  = today_candle["high"]
            low_price   = today_candle["low"]
            close_price = today_candle["close"]

            # Rule 2 (skip Rule 1 time gate - N/A for backtest)
            # Market cap check - skip since we pre-selected top stocks

            # Rule 3: Price in valid range
            if not (MIN_STOCK_PRICE <= open_price <= MAX_STOCK_PRICE):
                continue

            # Rule 4: Open = Low (Open Drive signal)
            tolerance = open_price * OPEN_LOW_TOLERANCE
            if abs(open_price - low_price) > tolerance:
                continue

            # Calculate pivot points from previous day
            prev_high  = prev_candle["high"]
            prev_low   = prev_candle["low"]
            prev_close = prev_candle["close"]
            PP, R1, R2, S1, S2 = calc_pivots(prev_high, prev_low, prev_close)

            # Entry price approximation:
            # On a real Open Drive day, by 9:30 the price has moved up
            # from open. We simulate entry at Open + 0.3% (conservative)
            entry = round(open_price * 1.003, 2)

            # Rule 5: Price > VWAP proxy
            # Early morning VWAP ~ between Open and entry
            # We use PP as VWAP proxy (institutional reference level)
            # In reality: VWAP at ~9:30 on open drive day ~ open * 1.001
            vwap_proxy = PP  # using pivot as the support/VWAP reference

            if entry <= vwap_proxy:
                continue

            # Rule 6: Price > PP
            if entry <= PP:
                continue

            # Rule 7: RSI >= WMA RSI
            indicators = stock_indicators.get(symbol)
            if indicators is None:
                continue

            rsi_val = indicators["rsi"].get(today_rows.index[0], np.nan)
            # For daily backtest, use previous day's RSI (since today hasn't closed yet at entry time)
            rsi_val = indicators["rsi"].get(prev_rows.index[-1], np.nan)
            wma_val = indicators["wma_rsi"].get(prev_rows.index[-1], np.nan)

            if pd.isna(rsi_val) or pd.isna(wma_val):
                continue
            if rsi_val < wma_val:
                continue

            # Rule 8: R:R >= 1.5
            risk_per_share = entry - vwap_proxy  # risk = entry - stop
            reward_per_share = R1 - entry

            if risk_per_share <= 0 or reward_per_share <= 0:
                continue

            rr_ratio = reward_per_share / risk_per_share
            if rr_ratio < MIN_RR_RATIO:
                continue

            # Rule 9: R1 >= 0.5% above entry
            r1_distance_pct = ((R1 - entry) / entry) * 100
            if r1_distance_pct < MIN_R1_DISTANCE_PCT:
                continue

            # ══════════════════════════════════════════════════════════════
            #  ALL RULES PASSED - Simulate the trade
            # ══════════════════════════════════════════════════════════════
            day_signals += 1

            # Position sizing (same as scanner.py)
            shares = int(MAX_RISK_PER_TRADE / risk_per_share)
            if shares <= 0:
                continue

            trade_value = shares * entry
            if trade_value > MAX_TRADE_VALUE:
                shares = int(MAX_TRADE_VALUE / entry)
                trade_value = shares * entry

            # --- FIX: Ensure we don't use more capital than we have ---
            available_capital = start_of_day_capital - daily_capital_used
            if trade_value > available_capital:
                # Reduce shares to fit available capital
                shares = int(available_capital / entry)
                trade_value = shares * entry
                
            if shares <= 0:
                continue
            
            # Record that we used this capital for the day
            daily_capital_used += trade_value

            t1_shares = max(1, int(shares * T1_EXIT_PCT))
            t2_shares = shares - t1_shares

            stop_loss = vwap_proxy

            # ── Exit Simulation using daily High/Low/Close ────────────
            #
            # Priority order (same as tracker.py):
            # 1. Stop hit (Low <= stop_loss)
            # 2. T2 hit (High >= R2 and we already hit T1)
            # 3. T1 hit (High >= R1)
            # 4. Time exit (close at end of day)
            #
            # Conservative assumption: if Low <= stop AND High >= R1
            # on same day, we assume STOP was hit first (worst case)

            trade_pnl = 0.0
            exit_type = ""
            exit_price = 0.0

            if low_price <= stop_loss:
                # STOPPED OUT - worst case assumption
                exit_price = stop_loss
                trade_pnl = shares * (stop_loss - entry)
                exit_type = "STOPPED"

            elif high_price >= R2:
                # Both T1 and T2 hit
                pnl_t1 = t1_shares * (R1 - entry)
                pnl_t2 = t2_shares * (R2 - entry)
                trade_pnl = pnl_t1 + pnl_t2
                exit_price = R2
                exit_type = "T2_HIT"

            elif high_price >= R1:
                # T1 hit, remaining exits at close (time stop)
                pnl_t1 = t1_shares * (R1 - entry)
                pnl_t2 = t2_shares * (close_price - entry)
                trade_pnl = pnl_t1 + pnl_t2
                exit_price = R1
                exit_type = "T1_HIT"

            else:
                # Neither target hit - time exit at close
                trade_pnl = shares * (close_price - entry)
                exit_price = close_price
                exit_type = "TIME_EXIT"

            trade_pnl = round(trade_pnl, 2)

            # Track daily loss
            if trade_pnl < 0:
                day_loss += abs(trade_pnl)
            else:
                day_gain += trade_pnl

            # Check daily loss limit
            if day_loss >= DAILY_LOSS_LIMIT:
                day_halted = True

            day_trades_taken += 1
            running_capital += trade_pnl

            # Record trade
            all_trades.append({
                "date":           str(today),
                "symbol":         symbol,
                "entry":          entry,
                "stop_loss":      stop_loss,
                "R1":             R1,
                "R2":             R2,
                "PP":             PP,
                "shares":         shares,
                "t1_shares":      t1_shares,
                "t2_shares":      t2_shares,
                "trade_value":    round(trade_value, 2),
                "risk_per_share": round(risk_per_share, 2),
                "rr_ratio":       round(rr_ratio, 2),
                "r1_dist_pct":    round(r1_distance_pct, 2),
                "rsi":            round(rsi_val, 2),
                "wma_rsi":        round(wma_val, 2),
                "exit_type":      exit_type,
                "exit_price":     round(exit_price, 2),
                "pnl":            trade_pnl,
                "max_loss":       round(shares * risk_per_share, 2),
                "high":           high_price,
                "low":            low_price,
                "close":          close_price,
            })

        # End of day equity
        equity_curve.append({
            "date": str(today),
            "equity": round(running_capital, 2),
        })

        daily_stats.append({
            "date":        str(today),
            "signals":     day_signals,
            "trades":      day_trades_taken,
            "gain":        round(day_gain, 2),
            "loss":        round(day_loss, 2),
            "net_pnl":     round(day_gain - day_loss, 2),
            "halted":      day_halted,
            "equity":      round(running_capital, 2),
        })

        # Progress update
        if (day_idx + 1) % 50 == 0:
            print(f"  Day {day_idx+1}/{len(trade_dates)} | "
                  f"Trades so far: {len(all_trades)} | "
                  f"Capital: Rs.{running_capital:,.0f}")

    # ══════════════════════════════════════════════════════════════════════
    #  RESULTS
    # ══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 60)
    print("  BACKTEST RESULTS")
    print("=" * 60)

    total_trades = len(all_trades)
    if total_trades == 0:
        print("  No trades were generated. Strategy may be too restrictive")
        print(f"  with the Open=Low tolerance of {OPEN_LOW_TOLERANCE*100:.2f}%.")
        print("  Try increasing OPEN_LOW_TOLERANCE in config.py.")
        return

    trades_df = pd.DataFrame(all_trades)

    # Win/Loss stats
    winners = trades_df[trades_df["pnl"] > 0]
    losers  = trades_df[trades_df["pnl"] < 0]
    breakeven = trades_df[trades_df["pnl"] == 0]

    win_rate = len(winners) / total_trades * 100

    # Exit type breakdown
    t1_hits  = len(trades_df[trades_df["exit_type"] == "T1_HIT"])
    t2_hits  = len(trades_df[trades_df["exit_type"] == "T2_HIT"])
    stops    = len(trades_df[trades_df["exit_type"] == "STOPPED"])
    time_exits = len(trades_df[trades_df["exit_type"] == "TIME_EXIT"])

    total_pnl = trades_df["pnl"].sum()
    avg_win   = winners["pnl"].mean() if len(winners) > 0 else 0
    avg_loss  = losers["pnl"].mean() if len(losers) > 0 else 0

    # Max drawdown
    equity_series = pd.Series([e["equity"] for e in equity_curve])
    running_max = equity_series.cummax()
    drawdown = (equity_series - running_max) / running_max * 100
    max_drawdown = drawdown.min()

    # Monthly P&L
    trades_df["month"] = pd.to_datetime(trades_df["date"]).dt.to_period("M")
    monthly_pnl = trades_df.groupby("month")["pnl"].sum()

    # Print results
    print(f"\n  PERFORMANCE SUMMARY")
    print(f"  -------------------")
    print(f"  Total Trades:        {total_trades}")
    print(f"  Winners:             {len(winners)} ({win_rate:.1f}%)")
    print(f"  Losers:              {len(losers)} ({100-win_rate:.1f}%)")
    print(f"  Breakeven:           {len(breakeven)}")
    print(f"")
    print(f"  Total P&L:           Rs.{total_pnl:,.2f}")
    print(f"  Return on Capital:   {(total_pnl/TOTAL_CAPITAL)*100:.2f}%")
    print(f"  Avg Win:             Rs.{avg_win:,.2f}")
    print(f"  Avg Loss:            Rs.{avg_loss:,.2f}")
    print(f"  Avg Win / Avg Loss:  {abs(avg_win/avg_loss) if avg_loss != 0 else 'N/A':.2f}")
    print(f"  Max Drawdown:        {max_drawdown:.2f}%")
    print(f"  Final Capital:       Rs.{running_capital:,.2f}")
    print(f"")
    print(f"  EXIT TYPE BREAKDOWN")
    print(f"  -------------------")
    print(f"  T1 Hit (R1):         {t1_hits} ({t1_hits/total_trades*100:.1f}%)")
    print(f"  T2 Hit (R2):         {t2_hits} ({t2_hits/total_trades*100:.1f}%)")
    print(f"  Stopped Out:         {stops} ({stops/total_trades*100:.1f}%)")
    print(f"  Time Exit (Close):   {time_exits} ({time_exits/total_trades*100:.1f}%)")
    print(f"")
    print(f"  MONTHLY P&L")
    print(f"  -------------------")
    for month, pnl in monthly_pnl.items():
        flag = "+" if pnl >= 0 else ""
        print(f"  {month}:  {flag}Rs.{pnl:,.2f}")

    # ── Save Results ──────────────────────────────────────────────────────
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Trade log
    trades_df.to_csv(os.path.join(RESULTS_DIR, "trades.csv"), index=False)

    # Equity curve
    pd.DataFrame(equity_curve).to_csv(
        os.path.join(RESULTS_DIR, "equity_curve.csv"), index=False
    )

    # Daily stats
    pd.DataFrame(daily_stats).to_csv(
        os.path.join(RESULTS_DIR, "daily_stats.csv"), index=False
    )

    # Summary JSON
    summary = {
        "period_start":     str(trade_dates[0]),
        "period_end":       str(trade_dates[-1]),
        "trading_days":     len(trade_dates),
        "stocks_scanned":   len(all_data),
        "total_trades":     total_trades,
        "winners":          len(winners),
        "losers":           len(losers),
        "win_rate":         round(win_rate, 2),
        "total_pnl":        round(total_pnl, 2),
        "return_pct":       round((total_pnl/TOTAL_CAPITAL)*100, 2),
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "final_capital":    round(running_capital, 2),
        "t1_hits":          t1_hits,
        "t2_hits":          t2_hits,
        "stops":            stops,
        "time_exits":       time_exits,
        "capital":          TOTAL_CAPITAL,
        "max_risk_per_trade": MAX_RISK_PER_TRADE,
    }

    with open(os.path.join(RESULTS_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n  Results saved to {RESULTS_DIR}/")
    print(f"    - trades.csv       ({total_trades} rows)")
    print(f"    - equity_curve.csv ({len(equity_curve)} points)")
    print(f"    - daily_stats.csv  ({len(daily_stats)} rows)")
    print(f"    - summary.json")
    print(f"\n  Run:  streamlit run backtest_app.py  to see the dashboard")
    print("=" * 60)


if __name__ == "__main__":
    run_backtest()
