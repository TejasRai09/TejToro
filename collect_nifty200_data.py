"""
collect_nifty200_data.py — Collect historical 10-min candle data for Nifty 200 stocks.

Fetches 1-min data from Upstox API in 29-day chunks, resamples to 10-min candles,
and saves to data/10min/{SYMBOL}.parquet. Supports incremental updates — only fetches
dates not already in the parquet file.

NOTE: token.txt must NEVER be committed to GitHub.
NOTE: If a parquet file has a hole (missing dates in the middle of the range),
      delete it and re-run to rebuild it cleanly.

Usage:
  python collect_nifty200_data.py --from 2025-01-01 --to 2025-03-31
  python collect_nifty200_data.py                    # last 60 days to today
  python collect_nifty200_data.py --from 2025-01-01  # from date to today
  python collect_nifty200_data.py --workers 6        # more parallelism
"""

import os
import sys
import time
import argparse
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instruments import load_instruments
from data_fetcher import _fetch_historical

ROOT       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(ROOT, "data", "10min")
NIFTY200   = 200
CHUNK_DAYS = 29  # Upstox 1-min API allows ~30 days per request; use 29 to be safe


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Strip timezone from DatetimeIndex so concat of pytz vs zoneinfo frames works."""
    if not df.empty and isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _resample_10min(df_1min: pd.DataFrame) -> pd.DataFrame:
    """Resample 1-min candles to 10-min, aligned to 9:15, 9:25, ... (same as data_fetcher)."""
    if df_1min.empty:
        return pd.DataFrame()
    df_10 = df_1min.resample("10min", offset="5min", closed="left", label="left").agg(
        open=("open",   "first"),
        high=("high",   "max"),
        low=("low",    "min"),
        close=("close", "last"),
        volume=("volume","sum"),
    ).dropna(subset=["close"])
    return _strip_tz(df_10.between_time("09:15", "15:20"))


def _date_chunks(from_d: date, to_d: date) -> list[tuple[date, date]]:
    """Split date range into CHUNK_DAYS-sized windows."""
    chunks, cur = [], from_d
    while cur <= to_d:
        end = min(cur + timedelta(days=CHUNK_DAYS), to_d)
        chunks.append((cur, end))
        cur = end + timedelta(days=1)
    return chunks


def _find_fetch_range(existing: pd.DataFrame, from_d: date, to_d: date):
    """
    Return (fetch_from, fetch_to) that covers all weekdays in [from_d, to_d]
    not already present in existing data. Returns None if nothing to fetch.
    """
    if existing.empty:
        return (from_d, to_d)

    existing_dates = set(existing.index.date)
    missing = [
        from_d + timedelta(days=i)
        for i in range((to_d - from_d).days + 1)
        if (from_d + timedelta(days=i)).weekday() < 5          # weekdays only
        and (from_d + timedelta(days=i)) not in existing_dates
    ]
    if not missing:
        return None
    return (min(missing), max(missing))


def _fetch_and_resample(instrument_key: str, from_d: date, to_d: date) -> pd.DataFrame:
    """Fetch 1-min data in CHUNK_DAYS windows, resample to 10-min, return combined."""
    parts = []
    for cf, ct in _date_chunks(from_d, to_d):
        df = _fetch_historical(
            instrument_key, "1minute",
            cf.strftime("%Y-%m-%d"), ct.strftime("%Y-%m-%d"),
        )
        if not df.empty:
            parts.append(df)
        time.sleep(0.15)   # small courtesy delay between chunk requests
    if not parts:
        return pd.DataFrame()
    raw = pd.concat(parts)
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    return _resample_10min(raw)


# ── Per-stock worker ──────────────────────────────────────────────────────────

def _process_stock(row: dict, from_d: date, to_d: date, idx: int, total: int) -> tuple[str, str]:
    sym  = row["symbol"]
    ikey = row["instrument_key"]
    path = os.path.join(DATA_DIR, f"{sym}.parquet")
    tag  = f"  [{idx:3d}/{total}] {sym:<16}"

    try:
        existing = _strip_tz(pd.read_parquet(path)) if os.path.exists(path) else pd.DataFrame()

        fetch_range = _find_fetch_range(existing, from_d, to_d)
        if fetch_range is None:
            first = existing.index[0].date()
            last  = existing.index[-1].date()
            print(f"{tag} SKIP  (have {first} to {last})")
            return sym, "skip"

        new_df = _fetch_and_resample(ikey, fetch_range[0], fetch_range[1])

        if new_df.empty and existing.empty:
            print(f"{tag} NO DATA")
            return sym, "no_data"

        parts  = [x for x in [existing, new_df] if not x.empty]
        merged = pd.concat(parts)
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()

        # Keep only the requested date window
        mask   = (merged.index.date >= from_d) & (merged.index.date <= to_d)
        merged = merged[mask]
        if merged.empty:
            print(f"{tag} NO DATA (empty after filter)")
            return sym, "no_data"

        os.makedirs(DATA_DIR, exist_ok=True)
        merged.to_parquet(path)

        days = len(set(merged.index.date))
        bars = len(merged)
        print(f"{tag} OK    ({days} trading days, {bars} bars)")
        return sym, "ok"

    except Exception as e:
        print(f"{tag} ERROR: {e}")
        return sym, "error"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Collect Nifty 200 historical 10-min data from Upstox")
    parser.add_argument("--from",    dest="from_date", default=None,
                        help="Start date YYYY-MM-DD (default: 60 days ago)")
    parser.add_argument("--to",      dest="to_date",   default=None,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel workers (default: 4 — keep low to respect rate limits)")
    args = parser.parse_args()

    to_d   = date.fromisoformat(args.to_date)   if args.to_date   else date.today()
    from_d = date.fromisoformat(args.from_date) if args.from_date else to_d - timedelta(days=60)

    print(f"\n  TejToro — Nifty 200 Data Collector")
    print(f"  Range  : {from_d} to {to_d}  ({(to_d - from_d).days + 1} calendar days)")
    print(f"  Workers: {args.workers}")
    print(f"  Output : {DATA_DIR}\n")

    df_inst  = load_instruments()
    universe = df_inst.head(NIFTY200).reset_index(drop=True)
    total    = len(universe)
    print(f"  Top {NIFTY200} stocks by market cap — {total} loaded\n")

    stats = {"ok": 0, "skip": 0, "no_data": 0, "error": 0}
    rows  = universe.to_dict("records")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(_process_stock, r, from_d, to_d, i + 1, total): r["symbol"]
            for i, r in enumerate(rows)
        }
        for f in as_completed(futs):
            _, status = f.result()
            stats[status] = stats.get(status, 0) + 1

    print(f"\n  Finished collecting data for {total} stocks.")
    print(f"  OK      : {stats['ok']}")
    print(f"  Skipped : {stats['skip']}  (already had complete data)")
    print(f"  No data : {stats['no_data']}")
    print(f"  Errors  : {stats['error']}")
    print(f"\n  Next step:")
    print(f"  python backtest.py --from {from_d} --to {to_d}\n")


if __name__ == "__main__":
    main()
