import yfinance as yf
import time
import concurrent.futures

tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ITC.NS", "WIPRO.NS", "SBIN.NS", "BHARTIARTL.NS"] * 10 # 80 tickers

def get_mcap(ticker):
    try:
        t = yf.Ticker(ticker)
        return t.info.get('marketCap', 0) / 10000000 # Convert to Crores
    except:
        return 0

start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(get_mcap, tickers))
print("Time taken:", time.time() - start)
print("Results:", results[:5])
