# ============================================================
#  config.py  —  All credentials and strategy parameters
#  SECURITY: Never commit this file to git or share publicly
# ============================================================

# ── Upstox OAuth2 ─────────────────────────────────────────────────────────
UPSTOX_API_KEY     = "63ab824b-1086-4adf-b3ab-cc08e93f5332"       # paste after Step 4
UPSTOX_API_SECRET  = "5wv21uf0z3"    # paste after Step 4
UPSTOX_REDIRECT_URI = "http://127.0.0.1:5000/callback"
TOKEN_FILE          = "token.txt"

# ── Telegram ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8787170403:AAEmm26hWONTm51H5fgRqLo9U5OGQTtuovU"
TELEGRAM_CHAT_ID   = "-5268589886"
TELEGRAM_TIMEOUT     = 20
TELEGRAM_RETRY_COUNT = 3
TELEGRAM_PROXY       = None

# ── Capital & Risk Management ─────────────────────────────────────────────
TOTAL_CAPITAL        = 200000   # ₹2,00,000
MAX_RISK_PER_TRADE   = 2000     # ₹2,000 = 1% of capital — max loss per trade
DAILY_LOSS_LIMIT     = 6000     # ₹6,000 = 3% of capital — system halts if hit
MAX_TRADES_PER_DAY   = 5        # hard cap on signals per day
MAX_SIMULTANEOUS     = 2        # max open positions at any time
MAX_TRADE_VALUE      = 150000   # ₹1,50,000 = 75% of capital max per trade

# ── Exit Split ────────────────────────────────────────────────────────────
T1_EXIT_PCT          = 0.60     # exit 60% of position at Target 1 (R1)
T2_EXIT_PCT          = 0.40     # exit remaining 40% at Target 2 (R2)

# ── Scanner Time Window ───────────────────────────────────────────────────
SCAN_START_TIME      = "09:20"  # scanner opens — first full 5-min candle available
SCAN_END_TIME        = "09:45"  # scanner closes — no new signals after this
MARKET_CLOSE_TIME    = "15:15"  # all open positions exited by this time

# ── Stock Universe Filters ────────────────────────────────────────────────
MIN_STOCK_PRICE      = 50.0     # ₹50 minimum — below this position sizing breaks
MAX_STOCK_PRICE      = 50000.0  # ₹50,000 maximum — essentially all stocks except MRF
MIN_MARKET_CAP_CR    = 500      # ₹500 Cr minimum market cap
MIN_DAILY_CHANGE_PCT = 1.0      # stock must be up >= 1% on the day (momentum filter)

# ── Signal Quality Filters ────────────────────────────────────────────────
MIN_RR_RATIO         = 1.5      # minimum Risk:Reward ratio — below this skip the trade
MIN_R1_DISTANCE_PCT  = 0.5      # R1 must be at least 0.5% above entry price
OPEN_LOW_TOLERANCE   = 0.0005   # 0.05% tolerance for Open = Low check
STOP_LOSS_PCT        = 0.01     # 1% fixed stop loss below entry price

# ── Indicator Periods ─────────────────────────────────────────────────────
RSI_PERIOD           = 14       # standard RSI period on 10-min candles
WMA_PERIOD           = 21       # WMA of RSI period

# ── Instruments File ──────────────────────────────────────────────────────
INSTRUMENTS_FILE     = "instruments.csv"
UPSTOX_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
