"""
notifier.py — Sends Telegram alerts for signals and position updates.

Three types of alerts:
    1. New signal found      — full trade card with all numbers
    2. Target hit            — tells you exactly how many shares to sell
    3. Stop hit              — tells you to exit immediately
    4. Time stop             — 3:15 PM forced exit reminder
    5. System alerts         — scanner open/close, daily loss limit hit

Your phone receives these. You read them. You act manually.
The alert tells you exactly what to do — no thinking required at that moment.
"""

import requests
import time
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_TIMEOUT,
    TELEGRAM_RETRY_COUNT,
    TELEGRAM_PROXY,
)


# ── Core Send Function ────────────────────────────────────────────────────

def _send(message: str) -> bool:
    """
    Sends a plain text message to your Telegram chat.
    Retries up to TELEGRAM_RETRY_COUNT times on non-429 errors.
    On 429, sleeps exactly retry_after seconds (from Telegram's response)
    then retries — 429s do NOT consume the retry counter.
    Returns True if sent successfully, False otherwise.
    """
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",
    }
    proxies = {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY} if TELEGRAM_PROXY else None
    errors  = 0

    while errors < TELEGRAM_RETRY_COUNT:
        try:
            resp = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT, proxies=proxies)
            if resp.status_code == 200:
                return True
            elif resp.status_code == 429:
                retry_after = resp.json().get("parameters", {}).get("retry_after", 15)
                print(f"   [WARN] Telegram rate limited. Retrying in {retry_after + 1}s...")
                time.sleep(retry_after + 1)   # +1 safety margin; does NOT count as error
            else:
                print(f"   [WARN] Telegram error: HTTP {resp.status_code} -- {resp.text}")
                errors += 1
        except Exception as e:
            print(f"   [WARN] Telegram send failed: {e}")
            errors += 1
            time.sleep(1)

    return False


# ── Alert Type 1: New Signal ──────────────────────────────────────────────

def alert_new_signal(signal: dict) -> bool:
    """
    Sends a full trade card when a new Open Drive signal is found.

    Everything the trader needs is in this one message:
        - What to buy and at what price
        - Exactly how many shares
        - Fixed stop loss (never changes)
        - Two targets with exact share quantities for each exit
        - Risk:Reward ratio
        - Max loss and max gain in rupees
    """
    sym         = signal["symbol"]
    entry       = signal["entry"]
    stop        = signal["stop_loss"]
    r1          = signal["R1"]
    r2          = signal["R2"]
    shares      = signal["shares"]
    t1_shares   = signal["t1_shares"]
    t2_shares   = signal["t2_shares"]
    trade_val   = signal["trade_value"]
    rr          = signal["rr_ratio"]
    max_loss    = signal["max_loss"]
    max_gain    = signal["max_gain"]
    rsi         = signal["rsi"]
    wma_rsi     = signal["wma_rsi"]
    mcap        = signal["market_cap_cr"]
    sig_time    = signal["signal_time"]
    r1_dist     = signal["r1_distance_pct"]
    
    live_open   = signal.get("live_open", 0)
    live_high   = signal.get("live_high", 0)
    live_low    = signal.get("live_low", 0)
    live_close  = signal.get("live_close", 0)
    live_vol    = signal.get("live_volume", 0)
    live_time   = signal.get("live_time", "N/A")
    
    first_open  = signal.get("first_open", 0)
    first_high  = signal.get("first_high", 0)
    first_low   = signal.get("first_low", 0)
    first_close = signal.get("first_close", 0)
    first_vol   = signal.get("first_volume", 0)
    first_time  = signal.get("first_time", "N/A")

    message = (
        f"🦅 *STRATEGY 1 — OPEN DRIVE SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{sym}*  |  {sig_time} IST\n"
        f"💹 Market Cap: ₹{mcap:,.0f} Cr\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕯️ *First Candle ({first_time}):*\n"
        f"O: {first_open:.2f} | H: {first_high:.2f}\n"
        f"L: {first_low:.2f} | C: {first_close:.2f}\n"
        f"V: {first_vol:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕯️ *Live Candle ({live_time}):*\n"
        f"O: {live_open:.2f} | H: {live_high:.2f}\n"
        f"L: {live_low:.2f} | C: {live_close:.2f}\n"
        f"V: {live_vol:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 *BUY:* ₹{entry:.2f}  ({shares} shares)\n"
        f"💰 *Trade Value:* ₹{trade_val:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ *STOP LOSS (fixed):* ₹{stop:.2f}\n"
        f"   _(Do NOT change this level)_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *TARGET 1 (R1):* ₹{r1:.2f}  (+{r1_dist:.1f}%)\n"
        f"   Sell *{t1_shares} shares* here\n"
        f"\n"
        f"🏆 *TARGET 2 (R2):* ₹{r2:.2f}\n"
        f"   Sell remaining *{t2_shares} shares* here\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 *Risk:Reward:* 1:{rr:.1f}\n"
        f"📉 *Max Loss:* ₹{max_loss:,.0f}\n"
        f"📈 *Max Gain:* ₹{max_gain:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 RSI: {rsi:.1f}  |  WMA RSI: {wma_rsi:.1f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ _Act within 60 seconds or skip this trade_"
    )

    return _send(message)


# ── Alert Type 2: Target 1 Hit ────────────────────────────────────────────

def alert_t1_hit(symbol: str, live_price: float, r1: float, t1_shares: int, t2_shares: int, r2: float) -> bool:
    """
    Fires when live price crosses R1.
    Tells trader exactly how many shares to sell now and how many to hold.
    """
    message = (
        f"🟢 *TARGET 1 HIT — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Current Price:* ₹{live_price:.2f}\n"
        f"✅ *R1 Level:* ₹{r1:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 *SELL NOW:* {t1_shares} shares\n"
        f"📌 *HOLD:* {t2_shares} shares for R2\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *Next Target (R2):* ₹{r2:.2f}\n"
        f"🛡️ Move stop to breakeven after selling"
    )
    return _send(message)


# ── Alert Type 3: Target 2 Hit ────────────────────────────────────────────

def alert_t2_hit(symbol: str, live_price: float, r2: float, t2_shares: int) -> bool:
    """
    Fires when live price crosses R2.
    Tells trader to exit the remaining position.
    """
    message = (
        f"🏆 *TARGET 2 HIT — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Current Price:* ₹{live_price:.2f}\n"
        f"✅ *R2 Level:* ₹{r2:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 *EXIT REMAINING:* {t2_shares} shares\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Trade Complete. Book full profit.*"
    )
    return _send(message)


# ── Alert Type 4: Stop Loss Hit ───────────────────────────────────────────

def alert_stop_hit(symbol: str, live_price: float, stop_loss: float, shares: int, loss: float) -> bool:
    """
    Fires when live price falls to or below the fixed stop loss.
    No ambiguity — exit immediately, full position.
    """
    message = (
        f"🩸 *STOP LOSS HIT — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 *Current Price:* ₹{live_price:.2f}\n"
        f"🛑 *Stop Level:* ₹{stop_loss:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 *EXIT ALL:* {shares} shares\n"
        f"💸 *Approx Loss:* ₹{loss:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ *Exit immediately. No averaging down.*"
    )
    return _send(message)


# ── Alert Type 5: Time Stop ───────────────────────────────────────────────

def alert_time_stop(symbol: str, shares: int, live_price: float) -> bool:
    """
    Fires at 3:15 PM for any position still open.
    All intraday positions must be closed before market close.
    """
    message = (
        f"⏰ *TIME STOP — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 *3:15 PM — Market closing soon*\n"
        f"💰 *Current Price:* ₹{live_price:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 *EXIT ALL:* {shares} shares\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *Close all intraday positions now.*"
    )
    return _send(message)


# ── Alert Type 6: System Alerts ───────────────────────────────────────────

def alert_scanner_open() -> bool:
    return _send(
        "🟢 *SCANNER OPEN*\n"
        "Open Drive scan window: 9:20 AM — 9:45 AM\n"
        "Watching for institutional accumulation signals..."
    )


def alert_scanner_closed(signals_found: int) -> bool:
    return _send(
        f"🔴 *SCANNER CLOSED*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Scan window closed at 9:45 AM\n"
        f"Signals found today: *{signals_found}*\n"
        f"Tracker remains active until 3:15 PM"
    )


def alert_daily_loss_limit(total_loss: float, limit: float) -> bool:
    return _send(
        f"🚨 *DAILY LOSS LIMIT HIT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total loss today: ₹{total_loss:,.0f}\n"
        f"Limit: ₹{limit:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛑 *System halted. No more trades today.*\n"
        f"Close any remaining positions manually."
    )


# ── Alert Type 7: Strategy 2 Convergence Signal ───────────────────────────

def alert_convergence_signal(signal: dict) -> bool:
    """Sends a Telegram alert when Strategy 2 finds a setup."""
    sym       = signal["symbol"]
    entry     = signal["entry"]
    mcap      = signal["market_cap_cr"]
    sig_time  = signal["signal_time"]
    stop      = signal["stop_loss"]
    r1        = signal["R1"]
    r2        = signal["R2"]
    shares    = signal["shares"]
    t1_shares = signal["t1_shares"]
    t2_shares = signal["t2_shares"]
    tv        = signal["trade_value"]
    rr        = signal["rr_ratio"]
    max_loss  = signal["max_loss"]
    max_gain  = signal["max_gain"]

    message = (
        f"🎯 *STRATEGY 2 — SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{sym}*  |  {sig_time} IST\n"
        f"💹 Market Cap: ₹{mcap:,.0f} Cr\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 *BUY:* ₹{entry:.2f}  ({shares} shares)\n"
        f"💰 *Trade Value:* ₹{tv:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ *STOP LOSS:* ₹{stop:.2f}\n"
        f"   _(Do NOT change this level)_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *TARGET 1:* ₹{r1:.2f}\n"
        f"   Sell *{t1_shares} shares* here\n"
        f"\n"
        f"🏆 *TARGET 2:* ₹{r2:.2f}\n"
        f"   Sell remaining *{t2_shares} shares* here\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 *Risk:Reward:* 1:{rr:.1f}\n"
        f"📉 *Max Loss:* ₹{max_loss:,.0f}\n"
        f"📈 *Max Gain:* ₹{max_gain:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ _Act within 60 seconds or skip this trade_"
    )
    return _send(message)


# ── Alert Type 8: Strategy 3 Multi-Strategy Signal ───────────────────────

def alert_strategy3_signal(signal: dict) -> bool:
    """Sends a Telegram alert for any Strategy 3 setup. No conditions revealed."""
    sym       = signal["symbol"]
    entry     = signal["entry"]
    mcap      = signal["market_cap_cr"]
    sig_time  = signal["signal_time"]
    stop      = signal["stop_loss"]
    r1        = signal["R1"]
    r2        = signal["R2"]
    shares    = signal["shares"]
    t1_shares = signal["t1_shares"]
    t2_shares = signal["t2_shares"]
    tv        = signal["trade_value"]
    rr        = signal["rr_ratio"]
    max_loss  = signal["max_loss"]
    max_gain  = signal["max_gain"]

    message = (
        f"⚡ *STRATEGY 3 — SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{sym}*  |  {sig_time} IST\n"
        f"💹 Market Cap: ₹{mcap:,.0f} Cr\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 *BUY:* ₹{entry:.2f}  ({shares} shares)\n"
        f"💰 *Trade Value:* ₹{tv:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ *STOP LOSS:* ₹{stop:.2f}\n"
        f"   _(Do NOT change this level)_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *TARGET 1:* ₹{r1:.2f}\n"
        f"   Sell *{t1_shares} shares* here\n"
        f"\n"
        f"🏆 *TARGET 2:* ₹{r2:.2f}\n"
        f"   Sell remaining *{t2_shares} shares* here\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 *Risk:Reward:* 1:{rr:.1f}\n"
        f"📉 *Max Loss:* ₹{max_loss:,.0f}\n"
        f"📈 *Max Gain:* ₹{max_gain:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ _Act within 60 seconds or skip this trade_"
    )
    return _send(message)


# ── Alert Type 9: Strategy 3 — VWAP Touch Entry ──────────────────────────

def alert_strategy3_vwap_touch(symbol: str, sig: dict, mcap: float) -> bool:
    """
    Fires when app3 detects the VWAP-touch entry pattern.

    Pattern:
        Candle A low ≤ VWAP  →  stock pulled back and tested VWAP
        Candle B close > Candle A high  →  bullish break confirmed
    Entry  : Candle B close
    SL     : VWAP (the level that was tested)
    Target : Entry + 3 × (Entry − SL)   →  1:3 R:R
    """
    entry      = sig["entry"]
    sl         = sig["sl"]
    target     = sig["target"]
    risk       = sig["risk"]
    reward     = sig["reward"]
    touch_time = sig["touch_time"]
    entry_time = sig["entry_time"]
    touch_vwap = sig["touch_vwap"]

    message = (
        f"⚡ *STRATEGY 3 — VWAP TOUCH BUY*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{symbol}*\n"
        f"💹 MCap: ₹{mcap:,.0f} Cr\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕯 *VWAP Touch:* {touch_time} candle\n"
        f"   Low touched VWAP @ ₹{touch_vwap}\n"
        f"✅ *Confirmed:* {entry_time} candle closed above previous high\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 *BUY @ ₹{entry:.2f}*\n"
        f"   _(at close of {entry_time} candle)_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ *STOP LOSS: ₹{sl:.2f}*\n"
        f"   VWAP — risk ₹{risk:.2f}/share\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *TARGET (1:3): ₹{target:.2f}*\n"
        f"   Reward ₹{reward:.2f}/share\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ _Act within 60 seconds or skip this trade_"
    )
    return _send(message)


# ── Alert Type 10: Strategy 3 — Target Hit ───────────────────────────────

def alert_strategy3_target_hit(symbol: str, live_price: float, sig: dict) -> bool:
    """Fires when live price reaches or exceeds the 1:3 target."""
    entry  = sig["entry"]
    target = sig["target"]
    sl     = sig["sl"]
    risk   = sig["risk"]
    reward = sig["reward"]
    gain   = round(live_price - entry, 2)

    message = (
        f"🎯 *TARGET HIT — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Current Price:* ₹{live_price:.2f}\n"
        f"✅ *Target (1:3):* ₹{target:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Entry: ₹{entry:.2f}\n"
        f"🛡️ Stop was: ₹{sl:.2f}  (risk ₹{risk:.2f}/share)\n"
        f"📈 Gain: ₹{gain:.2f}/share  ·  Reward ₹{reward:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 *Book profits now.*"
    )
    return _send(message)


# ── Alert Type 11: Strategy 3 — Stop Loss Hit ─────────────────────────────

def alert_strategy3_sl_hit(symbol: str, live_price: float, sig: dict) -> bool:
    """Fires when live price reaches or falls below the stop loss."""
    entry = sig["entry"]
    sl    = sig["sl"]
    risk  = sig["risk"]
    loss  = round(entry - live_price, 2)

    message = (
        f"🩸 *STOP LOSS HIT — {symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 *Current Price:* ₹{live_price:.2f}\n"
        f"🛑 *Stop Level:* ₹{sl:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Entry was: ₹{entry:.2f}\n"
        f"💸 Loss: ₹{loss:.2f}/share  (risk was ₹{risk:.2f})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ *Exit immediately. No averaging down.*"
    )
    return _send(message)


# ── Test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Quick test — run: python notifier.py
    Sends a test message to your Telegram chat.
    """
    print("Sending test message to Telegram...")
    success = _send(
        "✅ *Notifier Test*\n"
        "Your Open Drive tracker alerts are working correctly.\n"
        "You will receive trade signals here during market hours."
    )
    if success:
        print("[OK] Message sent successfully. Check your Telegram.")
    else:
        print("[ERROR] Failed to send. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in config.py")
