import sys
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
from instruments import load_instruments
from data_fetcher import get_market_quotes

df = load_instruments()
keys = df["instrument_key"].tolist()
quotes = get_market_quotes(keys[:50])

for api_key, data in quotes.items():
    token = data.get("instrument_token")
    ltp = data.get("last_price")
    net_change = data.get("net_change")
    print(f"{token} - ltp: {ltp}, net_change: {net_change}")
