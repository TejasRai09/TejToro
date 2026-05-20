"""
collect_data.py — Download 1 year of daily OHLCV data for backtesting.

Run:  python collect_data.py

Downloads daily candles for the top ~200 liquid NSE stocks
and saves them as individual CSV files in backtest_data/.
Uses your existing Upstox token (token.txt).
"""

import os
import sys
import time
import pandas as pd
from datetime import date, timedelta
from data_fetcher import _fetch_historical

# ── Config ────────────────────────────────────────────────────────────────
OUTPUT_DIR = "backtest_data"
DAYS_BACK  = 400   # ~1 year + buffer for indicator warmup

# Top ~200 liquid NSE stocks (Nifty 200 constituents + popular mid-caps)
# These are the stocks your scanner would actually find signals on.
TOP_STOCKS = [
    # Nifty 50
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC", "LT", "AXISBANK",
    "BAJFINANCE", "ASIANPAINT", "MARUTI", "HCLTECH", "SUNPHARMA",
    "TITAN", "WIPRO", "TATAMOTORS", "ULTRACEMCO", "NTPC", "POWERGRID",
    "NESTLEIND", "TECHM", "TATASTEEL", "ONGC", "JSWSTEEL",
    "BAJAJFINSV", "ADANIENT", "ADANIPORTS", "COALINDIA", "BPCL",
    "GRASIM", "CIPLA", "DRREDDY", "EICHERMOT", "DIVISLAB",
    "APOLLOHOSP", "HEROMOTOCO", "BRITANNIA", "TATACONSUM", "SBILIFE",
    "INDUSINDBK", "HINDALCO", "BAJAJ-AUTO",
    # Nifty Next 50
    "GODREJCP", "BERGEPAINT", "PIDILITIND", "HAVELLS", "DABUR",
    "SIEMENS", "ABB", "BOSCHLTD", "COLPAL", "MARICO", "AMBUJACEM",
    "SHREECEM", "ACC", "DLF", "TRENT", "INDIGO", "BANKBARODA",
    "PNB", "IOC", "GAIL", "HINDPETRO", "PETRONET", "MUTHOOTFIN",
    "CHOLAFIN", "SHRIRAMFIN", "HDFCLIFE", "ICICIGI", "ICICIPRULI",
    "PFC", "RECLTD", "IRFC", "NHPC", "TATAPOWER", "ADANIPOWER",
    "ADANIGREEN", "VEDL", "JINDALSTEL", "SAIL", "NATIONALUM",
    "HINDZINC", "NMDC", "ZOMATO", "NYKAA", "PAYTM", "DELHIVERY",
    "POLICYBZR", "ZYDUSLIFE", "LUPIN", "BIOCON", "AUROPHARMA",
    "TORNTPHARM", "ALKEM", "IPCALAB", "LAURUSLABS",
    # Popular Mid-caps & Small-caps (in your price range ₹50-₹1500)
    "TATAELXSI", "MPHASIS", "LTIM", "PERSISTENT", "COFORGE",
    "MINDTREE", "DEEPAKFERT", "DEEPAKNI", "ATUL", "PIIND",
    "SYNGENE", "LALPATHLAB", "METROPOLIS", "MAXHEALTH",
    "ASTRAL", "SUPREMEIND", "POLYCAB", "VOLTAS", "BLUESTARLT",
    "CROMPTON", "WHIRLPOOL", "DIXON", "KAYNES", "ELGIEQUIP",
    "CUMMINSIND", "THERMAX", "BEL", "HAL", "BDL", "COCHINSHIP",
    "GRINDWELL", "CARBORUNIV", "SCHAEFFLER", "TIMKEN", "SKFINDIA",
    "FAGBEARING", "SUNTV", "PVRINOX", "ZEEL", "CDSL", "BSE",
    "MCX", "ANGELONE", "IRCTC", "CONCOR", "GMRINFRA",
    "SONATSOFTW", "HAPPSTMNDS", "KPITTECH", "CYIENT", "BIRLASOFT",
    "ZENSAR", "MFSL", "IIFL", "MANAPPURAM", "POONAWALLA",
    "CANFINHOME", "AAVAS", "HOMEFIRST", "APTUS",
    "OBEROIRLTY", "GODREJPROP", "PRESTIGE", "PHOENIXLTD", "LODHA",
    "DEVYANI", "JUBLFOOD", "WESTLIFE", "SAPPHIRE", "PATANJALI",
    "HONASA", "RAYMOND", "PAGEIND", "ABFRL", "TRENT",
    "CELLO", "STARHEALTH", "NIACL", "SBICARD", "HDFCAMC",
    "ICICIAMC", "UTIAMC", "CAMS", "KFINTECH",
    "INDIAMART", "JUSTDIAL", "NAUKRI", "TATACHEM", "NAVINFLUOR",
    "CLEAN", "FLUOROCHEM", "SRF", "UPL", "SUMICHEM",
    "CENTRALBK", "UNIONBANK", "INDIANB", "IDFCFIRSTB", "FEDERALBNK",
    "BANDHANBNK", "RBLBANK", "KARURVYSYA", "CANBK",
    "MGL", "IGL", "GUJGASLTD", "GSPL",
    "TATACOMM", "RAILTEL", "HFCL", "STLTECH",
    "ESCORTS", "ASHOKLEY", "MAHINDCIE", "FORCEMOT",
    "NUVAMA", "FIVESTAR", "EQUITASBNK", "UJJIVANSFB",
    "SUNDARMFIN", "ABCAPITAL", "BAJAJHLDNG",
    "PGHL", "GILLETTE", "EMAMILTD", "VGUARD", "KANSAINER",
]

# Remove duplicates
TOP_STOCKS = list(dict.fromkeys(TOP_STOCKS))


def build_instrument_key_map() -> dict:
    """Build symbol → instrument_key mapping from instruments.csv"""
    csv_path = "instruments.csv"
    if not os.path.exists(csv_path):
        print("❌ instruments.csv not found. Run build_instruments.py first.")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df = df.dropna(subset=["symbol", "instrument_key"])
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()

    key_map = {}
    for _, row in df.iterrows():
        key_map[row["symbol"]] = row["instrument_key"]

    return key_map


def collect():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    key_map = build_instrument_key_map()

    # Filter to stocks that exist in instruments.csv
    valid_stocks = [s for s in TOP_STOCKS if s in key_map]
    missing = [s for s in TOP_STOCKS if s not in key_map]

    total = len(valid_stocks)

    print("=" * 60)
    print("  COLLECTING DAILY DATA FOR BACKTESTING")
    print(f"  Stocks to fetch: {total}")
    if missing:
        print(f"  Not found in instruments.csv: {len(missing)}")
    print(f"  Period: ~1 year ({(date.today() - timedelta(days=DAYS_BACK)).strftime('%Y-%m-%d')} to {date.today().strftime('%Y-%m-%d')})")
    print(f"  Output: {os.path.abspath(OUTPUT_DIR)}/")
    print("=" * 60)

    today_str = date.today().strftime("%Y-%m-%d")
    from_str  = (date.today() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    success = 0
    failed  = 0
    skipped = 0

    for i, symbol in enumerate(valid_stocks):
        csv_path = os.path.join(OUTPUT_DIR, f"{symbol}.csv")

        # Skip if already downloaded with enough data
        if os.path.exists(csv_path):
            try:
                existing = pd.read_csv(csv_path, index_col=0)
                if len(existing) >= 200:
                    skipped += 1
                    if (i + 1) % 20 == 0:
                        print(f"   [{i+1}/{total}] ... (skipping existing)")
                    continue
            except:
                pass

        instrument_key = key_map[symbol]

        try:
            df = _fetch_historical(instrument_key, "day", from_str, today_str)

            if df.empty or len(df) < 50:
                failed += 1
                print(f"   [{i+1}/{total}] {symbol}: FAIL - insufficient data ({len(df)} rows)")
                continue

            df.to_csv(csv_path)
            success += 1
            print(f"   [{i+1}/{total}] {symbol}: OK - {len(df)} daily candles")

        except Exception as e:
            failed += 1
            print(f"   [{i+1}/{total}] {symbol}: FAIL - {e}")

        # Small delay to respect API limits
        time.sleep(0.5)

    print(f"\n{'=' * 60}")
    print(f"  COLLECTION COMPLETE")
    print(f"  Downloaded: {success}")
    print(f"  Already had: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Data: {os.path.abspath(OUTPUT_DIR)}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    collect()
