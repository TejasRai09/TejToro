
import pandas as pd
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

import data_fetcher
from instruments import load_instruments

def check_bins():
    instruments = load_instruments()
    symbol = "COFORGE"
    row = instruments[instruments['symbol'] == symbol].iloc[0]
    key = row['instrument_key']
    
    print(f"Fetching candles for {symbol}...")
    df = data_fetcher.get_10min_candles(key, days_back=1)
    
    print("\nFirst 5 candles of today:")
    print(df.head(5))
    
    # Check raw data to see where 09:15 goes
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    raw_1m = data_fetcher._fetch_intraday(key)
    print("\nRaw 1m data around 09:15:")
    print(raw_1m.between_time("09:15", "09:25").head(10))

if __name__ == "__main__":
    check_bins()
