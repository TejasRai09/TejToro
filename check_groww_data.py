
import requests
import pandas as pd
from datetime import datetime
from auth import load_token

def check_groww_1min():
    token = load_token()
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    instrument_key = "NSE_EQ|INE0HOQ01053"
    to_date = "2026-04-24"
    from_date = "2026-04-24"
    
    url = f"https://api-v2.upstox.com/historical-candle/{instrument_key}/1minute/{to_date}/{from_date}"
    
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Error: {resp.status_code}")
        return
        
    candles = resp.json().get("data", {}).get("candles", [])
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    
    print("GROWW 1-min candles for April 24 morning:")
    print(df[df["timestamp"].dt.time < datetime.strptime("09:30", "%H:%M").time()].to_string(index=False))

if __name__ == "__main__":
    check_groww_1min()
