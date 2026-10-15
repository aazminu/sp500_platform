# quick_data_diagnostics.py
# ------------------------------------------------------------
# Purpose: sanity-check OHLC price data for spikes, splits, gaps, duplicates
# Usage:   python quick_data_diagnostics.py
# Requires: pandas, numpy, sqlalchemy (if using DB)
# ------------------------------------------------------------

import os
import math
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# ==================== CONFIG ====================
# Load .env from current directory (util scripts folder)
load_dotenv()

USE_DB = True  # Set False to use CSV fallback
DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:pass@host:5432/dbname")

# Table/column assumptions (adjust if your schema differs)
PRICES_TABLE = "prices"
COL_TICKER = "ticker"
COL_DATE = "price_date"  # Fixed: your schema uses price_date, not date
COL_CLOSES = ["close_price", "close", "price"]  # we will pick the first that exists

# Date window to inspect (expand if needed)
START_DATE = "2025-08-01"
END_DATE   = "2025-09-20"

# CSV fallback path (only used if USE_DB=False)
CSV_PATH = "prices.csv"

# Thresholds
RET_THRESHOLD = 0.20    # 20% daily move gets flagged
WEEK_RET_THRESHOLD = 0.40
SPLIT_TOL = 0.03        # 3% tolerance around common split ratios
COMMON_SPLITS = [2.0, 3.0, 4.0, 5.0]  # also checks inverse (1/ratio)

# =================================================

def pick_close_col(df):
    for c in COL_CLOSES:
        if c in df.columns:
            return c
    raise ValueError(f"No close column found. Tried: {COL_CLOSES}")

def load_prices():
    if USE_DB:
        from sqlalchemy import create_engine, text
        eng = create_engine(DB_URL)
        q = f"""
        SELECT {COL_TICKER} AS ticker, {COL_DATE} AS date, 
               open_price, high_price, low_price, close_price, volume
        FROM {PRICES_TABLE}
        WHERE {COL_DATE} BETWEEN :start AND :end
        """
        df = pd.read_sql(text(q), eng, params={"start": START_DATE, "end": END_DATE})
    else:
        df = pd.read_csv(CSV_PATH, parse_dates=[COL_DATE])
        df = df[(df[COL_DATE] >= START_DATE) & (df[COL_DATE] <= END_DATE)].copy()
    # Canonicalize
    if "ticker" not in df.columns:
        df = df.rename(columns={COL_TICKER: "ticker"})
    if "date" not in df.columns:
        df = df.rename(columns={COL_DATE: "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df

def flag_duplicates(df):
    dups = df.duplicated(subset=["ticker", "date"], keep=False)
    return df.loc[dups, ["ticker","date"]].sort_values(["ticker","date"]).drop_duplicates()

def flag_nonpositive(df, close_col):
    return df.loc[~(df[close_col] > 0), ["ticker","date", close_col]].sort_values(["ticker","date"])

def compute_daily_returns(df, close_col):
    df = df.sort_values(["ticker","date"]).copy()
    df["prev_close"] = df.groupby("ticker")[close_col].shift(1)
    df["ret"] = (df[close_col] - df["prev_close"]) / df["prev_close"]
    return df

def flag_big_moves(df):
    return df.loc[df["ret"].abs() >= RET_THRESHOLD, ["ticker","date","prev_close","ret"]].sort_values("date")

def detect_splits(df, close_col):
    # If ratio close/prev_close ~ 1/s OR s, mark as probable split
    out = []
    for s in COMMON_SPLITS:
        up_ratio_low  = (1/s) - SPLIT_TOL
        up_ratio_high = (1/s) + SPLIT_TOL
        dn_ratio_low  = s - s*SPLIT_TOL
        dn_ratio_high = s + s*SPLIT_TOL
        # Using ratio old/new: prev_close / close
        ratio = df["prev_close"] / df[close_col]
        mask_up = ratio.between(up_ratio_low, up_ratio_high)   # forward split
        mask_dn = ratio.between(dn_ratio_low, dn_ratio_high)   # reverse split
        tmp = df.loc[mask_up | mask_dn, ["ticker","date","prev_close",close_col]].copy()
        if not tmp.empty:
            tmp["split_guess"] = np.where(mask_up.loc[tmp.index], f"~{s}:1 (forward?)", f"~1:{s} (reverse?)")
            out.append(tmp)
    if out:
        return pd.concat(out).sort_values(["ticker","date"])
    return pd.DataFrame(columns=["ticker","date","prev_close",close_col,"split_guess"])

def flag_missing_days(df):
    # For each ticker, compare available dates to a union calendar; report gaps > 3 trading days
    gaps = []
    for t, g in df.groupby("ticker"):
        g = g.sort_values("date")
        # Business days may not match trading days perfectly; this is a heuristic.
        delta = g["date"].diff().dt.days
        big = g.loc[delta >= 5, ["ticker","date"]].copy()
        if not big.empty:
            big["gap_days"] = delta.loc[big.index]
            gaps.append(big)
    if gaps:
        return pd.concat(gaps).sort_values(["ticker","date"])
    return pd.DataFrame(columns=["ticker","date","gap_days"])

def weekly_returns(df, close_col):
    df["week"] = df["date"].dt.to_period("W").apply(lambda r: r.end_time.normalize())
    wk = df.sort_values(["ticker","date"]).groupby(["ticker","week"]).apply(
        lambda x: (x.iloc[-1][close_col] / x.iloc[0][close_col]) - 1.0
    ).rename("week_ret").reset_index()
    return wk

def flag_big_weekly_moves(wk):
    return wk.loc[wk["week_ret"].abs() >= WEEK_RET_THRESHOLD].sort_values(["week","ticker"])

def top_n_moves(df, n=10):
    return df.dropna(subset=["ret"]).assign(abs_ret=lambda x: x["ret"].abs()) \
             .sort_values("abs_ret", ascending=False).head(n) \
             [["ticker","date","prev_close","ret"]]

def main():
    print("Loading data...")
    df = load_prices()
    close_col = pick_close_col(df)
    df = df[["ticker","date",close_col]].dropna()
    print(f"Using close column: {close_col}")

    print("\n1) Checking duplicates (ticker, date)...")
    dups = flag_duplicates(df)
    print(f"  Duplicates found: {len(dups)}")
    if not dups.empty:
        print(dups.head(20).to_string(index=False))

    print("\n2) Checking nonpositive prices...")
    badp = flag_nonpositive(df, close_col)
    print(f"  Nonpositive rows: {len(badp)}")
    if not badp.empty:
        print(badp.head(20).to_string(index=False))

    print("\n3) Computing daily returns...")
    dr = compute_daily_returns(df, close_col)

    print("\n4) Flagging suspicious daily moves (>|20%|)...")
    big = flag_big_moves(dr)
    print(f"  Big daily moves: {len(big)}")
    if not big.empty:
        print(big.head(30).to_string(index=False))

    print("\n5) Detecting probable splits...")
    splits = detect_splits(dr, close_col)
    print(f"  Split-like events: {len(splits)}")
    if not splits.empty:
        print(splits.head(20).to_string(index=False))

    print("\n6) Checking large date gaps per ticker (>= 5 days)...")
    gaps = flag_missing_days(df)
    print(f"  Large gaps: {len(gaps)}")
    if not gaps.empty:
        print(gaps.head(20).to_string(index=False))

    print("\n7) Weekly return outliers (>|40%|)...")
    wk = weekly_returns(df, close_col)
    wk_big = flag_big_weekly_moves(wk)
    print(f"  Big weekly moves: {len(wk_big)}")
    if not wk_big.empty:
        print(wk_big.head(30).to_string(index=False))

    print("\n8) Top 10 absolute daily movers (sanity check):")
    print(top_n_moves(dr, n=10).to_string(index=False))

    # Optional: export details for deeper inspection
    outdir = "diagnostics_out"
    os.makedirs(outdir, exist_ok=True)
    big.to_csv(f"{outdir}/daily_big_moves.csv", index=False)
    splits.to_csv(f"{outdir}/probable_splits.csv", index=False)
    gaps.to_csv(f"{outdir}/large_gaps.csv", index=False)
    wk_big.to_csv(f"{outdir}/weekly_big_moves.csv", index=False)
    dups.to_csv(f"{outdir}/duplicates.csv", index=False)
    badp.to_csv(f"{outdir}/nonpositive_prices.csv", index=False)
    print(f"\nSaved CSVs to {outdir}/")

if __name__ == "__main__":
    main()
