
import pandas as pd
from datetime import time

def debug_app1_data():
    file_path = "backtest_30d/COFORGE.csv"
    if not os.path.exists(file_path):
        print("COFORGE data not found.")
        return

    df = pd.read_csv(file_path)
    if 'timestamp' in df.columns:
        df = df.rename(columns={'timestamp': 'datetime'})
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    
    df_10m = df.resample("10min", closed="left", label="left").agg({"open":"first", "low":"min"})
    
    dates = df_10m.index.normalize().unique()
    print(f"Checking {len(dates)} days for COFORGE:")
    for d in dates:
        day_data = df_10m[df_10m.index.normalize() == d]
        if day_data.empty: continue
        
        first = day_data.iloc[0]
        print(f"  {d.date()} | Time: {first.name.time()} | O: {first['open']} | L: {first['low']} | Diff: {abs(first['open']-first['low'])}")

import os
if __name__ == "__main__":
    debug_app1_data()
