import sys
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
from instruments import load_instruments
from scanner import prefilter_by_quotes, evaluate_stock

df = load_instruments()
print("Instruments loaded:", len(df))
passed = prefilter_by_quotes(df)
print("Prefilter passed:", len(passed))

failed_counts = {"None": 0, "Valid": 0}
for i, s in enumerate(passed[:50]): # Check first 50
    res = evaluate_stock(s['symbol'], s['instrument_key'], s['market_cap_cr'])
    if res is None:
        failed_counts["None"] += 1
    else:
        failed_counts["Valid"] += 1
        print("VALID SIGNAL:", s['symbol'])

print("Counts:", failed_counts)
