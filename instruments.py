import pandas as pd
import os
import sys
from config import INSTRUMENTS_FILE, MIN_MARKET_CAP_CR

def load_instruments():
    # Check file exists
    if not os.path.exists(INSTRUMENTS_FILE):
        print("=" * 60)
        print("  [ERROR] instruments.csv NOT FOUND")
        print("  Run this command first:")
        print("      python build_instruments.py")
        print("=" * 60)
        sys.exit(1)

    df = pd.read_csv(INSTRUMENTS_FILE)

    # Validate required columns
    required = ["symbol", "instrument_key", "market_cap_cr"]
    for col in required:
        if col not in df.columns:
            print(f"[ERROR] Missing column: {col}")
            sys.exit(1)

    # Clean data
    df = df.dropna(subset=["symbol", "instrument_key"])
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["instrument_key"] = df["instrument_key"].astype(str).str.strip()
    df["market_cap_cr"] = pd.to_numeric(df["market_cap_cr"], errors="coerce").fillna(0)

    # Remove junk symbols (like bonds)
    df = df[df["symbol"].str.match(r"^[A-Z]+$", na=False)]

    # Apply market cap filter only if valid data exists
    if df["market_cap_cr"].sum() > 0:
        df = df[df["market_cap_cr"] >= MIN_MARKET_CAP_CR]
    else:
        print("[WARN] Market cap data not available -- skipping filter")

    # Sort
    df = df.sort_values("market_cap_cr", ascending=False).reset_index(drop=True)

    return df


if __name__ == "__main__":
    df = load_instruments()

    print(f"✅ Loaded {len(df)} instruments from {INSTRUMENTS_FILE}")

    print("\nTop 10:")
    print(df.head(10).to_string(index=False))

    print("\nBottom 10:")
    print(df.tail(10).to_string(index=False))