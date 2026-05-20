
import pandas as pd
from zoneinfo import ZoneInfo
from indicators import prepare_indicators

IST = ZoneInfo("Asia/Kolkata")
df_1m = pd.read_csv("nifty500_data/GROWW.csv")
df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
df_1m.set_index('datetime', inplace=True)

df_10m = df_1m.resample("10min", closed="left", label="left").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
}).dropna()

df_history = df_10m[df_10m.index.normalize() <= pd.Timestamp("2026-04-15")].copy()
today_indicators, pivots = prepare_indicators(df_history)

print("Index for April 15:")
print(today_indicators[today_indicators.index.normalize() == pd.Timestamp("2026-04-15")].index)

print("\nValues at 09:15:")
try:
    print(today_indicators.loc[pd.Timestamp("2026-04-15 09:15:00").tz_localize(IST)])
except:
    print("Not found")

print("\nPivots:")
print(pivots)
