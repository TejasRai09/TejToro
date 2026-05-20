
import pandas as pd
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
df_1m = pd.read_csv("nifty500_data/GROWW.csv")
df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
df_1m.set_index('datetime', inplace=True)

df_10m = df_1m.resample("10min", closed="left", label="left").agg({
    "open": "first", "high": "max", "low": "min", "close": "last"
}).dropna()

days = df_10m.index.normalize().unique()
for d in days:
    day_data = df_10m[df_10m.index.normalize() == d]
    if day_data.empty: continue
    first = day_data.iloc[0]
    diff = abs(first['open'] - first['low'])
    tol = first['open'] * 0.0005
    print(f"Date: {d.date()} | Open: {first['open']:.2f} | Low: {first['low']:.2f} | Diff: {diff:.4f} | Tol: {tol:.4f} | Pass: {diff <= tol}")
