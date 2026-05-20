
import pandas as pd
from zoneinfo import ZoneInfo
from indicators import prepare_indicators
from config import OPEN_LOW_TOLERANCE

IST = ZoneInfo("Asia/Kolkata")
df_1m = pd.read_csv("nifty500_data/GROWW.csv")
df_1m['datetime'] = pd.to_datetime(df_1m['datetime'])
df_1m.set_index('datetime', inplace=True)
df_10m = df_1m.resample("10min", closed="left", label="left").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
}).dropna()

df_subset = df_10m[df_10m.index.normalize() <= pd.Timestamp("2026-04-15").tz_localize(IST)].copy()
today_indicators, pivots = prepare_indicators(df_subset)

day_data = today_indicators[today_indicators.index.normalize() == pd.Timestamp("2026-04-15").tz_localize(IST)]
R1 = pivots['R1']
PP = pivots['PP']

print(f"Pivots: PP={PP}, R1={R1}")
for ts, row in day_data.iterrows():
    ltp = row['close']
    vwap = row['vwap']
    rsi = row['rsi']
    wma = row['wma_rsi']
    
    risk = ltp - vwap
    reward = R1 - ltp
    rr = reward/risk if risk > 0 else 0
    
    print(f"Time: {ts.time()} | LTP: {ltp:.2f} | VWAP: {vwap:.2f} | RSI: {rsi:.2f} | WMA: {wma:.2f} | RR: {rr:.2f} | Above PP: {ltp > PP}")
