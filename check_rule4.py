import sys
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

from data_fetcher import get_market_quotes, get_10min_candles
from indicators import prepare_indicators
from instruments import load_instruments
from config import OPEN_LOW_TOLERANCE
import pandas as pd
import concurrent.futures

df = load_instruments()
print(f"Checking Rule 4 (Open=Low) for all {len(df)} stocks...")

def check_rule4(row):
    sym = row['symbol']
    key = row['instrument_key']
    try:
        candles = get_10min_candles(key)
        if candles.empty: return None
        
        # We only need the first candle of today
        # data_fetcher.get_10min_candles returns 2-3 days of data
        current_date = candles.index[-1].date()
        today_df = candles[candles.index.date == current_date]
        if today_df.empty: return None
        
        first_candle = today_df.iloc[0]
        first_open = first_candle["open"]
        first_low  = first_candle["low"]
        tolerance  = first_open * OPEN_LOW_TOLERANCE
        
        if abs(first_open - first_low) <= tolerance:
            return sym
    except:
        pass
    return None

results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(check_rule4, [row for _, row in df.iterrows()]))

passed = [r for r in results if r is not None]
print(f"\nStocks that passed Rule 4 (Open=Low): {len(passed)}")
if passed:
    print(", ".join(passed[:20]))
else:
    print("None found.")
