import os, sys, requests, datetime as dt
from decimal import Decimal
import pytz
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

"""
What it does: Fetches daily portfolio equity and benchmark data from Alpaca and FMP APIs, storing daily snapshots for performance analysis.
How it works: Gets historical equity data from Alpaca portfolio history and SPY prices from FMP, then stores daily snapshots in nav_weekly and benchmark_weekly tables.
Data storage: Stores records in nav_weekly and benchmark_weekly tables with daily equity/price data, using upsert logic to avoid duplicates.
"""

# Load environment variables
load_dotenv(override=True)

DB_URL = os.getenv("DATABASE_URL")
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_BASE = os.getenv("ALPACA_BASE", "https://paper-api.alpaca.markets")

if not DB_URL:
    raise SystemExit("Missing DATABASE_URL")

NY = pytz.timezone("America/New_York")
engine = create_engine(DB_URL, pool_pre_ping=True)

# ----------------- Time helpers -----------------
def to_et(d: dt.datetime) -> dt.datetime:
    return d.astimezone(NY)

def is_weekday(date: dt.date) -> bool:
    """Check if a date is a weekday (Monday=0, Sunday=6)."""
    return date.weekday() < 5  # Monday=0, Tuesday=1, ..., Friday=4

def daily_keys_between(start_date: dt.date, end_date: dt.date):
    """All dates (inclusive) between start and end - weekdays only."""
    d = start_date
    keys = []
    while d <= end_date:
        if is_weekday(d):  # Only include trading days
            keys.append(d)
        d += dt.timedelta(days=1)
    return keys

# ----------------- Data fetchers -----------------
def get_alpaca_equity_series(days: int):
    """
    STRICT historical pull from Alpaca portfolio history.
    Returns list[(date_ET, Decimal equity)] for the last N calendar days.
    """
    if not (ALPACA_KEY and ALPACA_SECRET):
        raise RuntimeError("Alpaca credentials missing")
    
    end_utc = dt.datetime.now(dt.timezone.utc)
    start_utc = end_utc - dt.timedelta(days=max(days, 1) + 14)  # + buffer for weekends/holidays

    base_url = f"{ALPACA_BASE}/v2/account/portfolio/history"
    headers = {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }
    params = {
        "timeframe": "1D",  # EOD equity per trading day
        "date_start": start_utc.strftime("%Y-%m-%d"),
        "date_end":   end_utc.strftime("%Y-%m-%d"),
    }

    r = requests.get(base_url, headers=headers, params=params, timeout=30)
    try:
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Alpaca portfolio history HTTP error: {e} | url={r.url} | body={r.text[:500]}")

    j = r.json()
    stamps = j.get("timestamp", [])
    equities = j.get("equity", [])
    
    print(f"🔍 Alpaca API Debug:")
    print(f"   Requested date range: {params['date_start']} to {params['date_end']}")
    print(f"   Timestamps returned: {len(stamps)}")
    print(f"   Equities returned: {len(equities)}")

    if not equities or not stamps:
        raise RuntimeError(
            "Alpaca returned empty portfolio history. "
            f"Checked timeframe=1D, date_start={params['date_start']}, date_end={params['date_end']}. "
            f"URL={r.url} RESPONSE_KEYS={list(j.keys())}"
        )

    # Convert UNIX seconds -> ET date; coalesce one value per date
    out = []
    for ts, eq in zip(stamps, equities):
        d_utc = dt.datetime.utcfromtimestamp(ts).replace(tzinfo=dt.timezone.utc)
        d_et = d_utc.astimezone(NY).date()
        # Only include trading days to avoid weekend contamination
        if is_weekday(d_et):
            out.append((d_et, Decimal(str(eq))))

    coalesced = {}
    for d, eq in out:
        coalesced[d] = eq

    series = sorted(coalesced.items())
    # Trim to the requested window (soft guard)
    cutoff = (end_utc.astimezone(NY).date() - dt.timedelta(days=days + 14))
    return [p for p in series if p[0] >= cutoff]

def get_fmp_spy_adj_close(days: int):
    """
    Returns list of (date, adj_close_decimal) for SPY for ~N days (trading days).
    """
    if not FMP_KEY:
        return []
    # pull a buffer to be safe
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/SPY?serietype=line&timeseries={max(days+10, 30)}&apikey={FMP_KEY}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    hist = r.json().get("historical", [])
    out = []
    for row in hist:
        d = dt.date.fromisoformat(row["date"])
        # Only include trading days to avoid weekend contamination
        if is_weekday(d):
            adj = Decimal(str(row.get("adjClose", row.get("close"))))
            out.append((d, adj))
    # API returns newest→oldest; sort oldest→newest
    return sorted(out)

# ----------------- Weekend data cleaning -----------------
def clean_weekend_data():
    """
    Remove any weekend data that might be contaminating p-value calculations.
    This ensures only trading days are used for statistical analysis.
    """
    try:
        with engine.begin() as conn:
            # Delete weekend data from nav_weekly
            weekend_nav_deleted = conn.execute(text("""
                DELETE FROM nav_weekly 
                WHERE EXTRACT(DOW FROM week_start_date) IN (0, 6)
            """)).rowcount
            
            # Delete weekend data from benchmark_weekly
            weekend_bench_deleted = conn.execute(text("""
                DELETE FROM benchmark_weekly 
                WHERE EXTRACT(DOW FROM week_start_date) IN (0, 6)
            """)).rowcount
            
            # Delete weekend data from weekly_stats
            weekend_stats_deleted = conn.execute(text("""
                DELETE FROM weekly_stats 
                WHERE EXTRACT(DOW FROM week_start_date) IN (0, 6)
            """)).rowcount
            
            if weekend_nav_deleted > 0 or weekend_bench_deleted > 0 or weekend_stats_deleted > 0:
                print(f"[INFO] Cleaned weekend data: {weekend_nav_deleted} nav records, {weekend_bench_deleted} benchmark records, {weekend_stats_deleted} stats records")
            else:
                print("[OK] No weekend data found to clean")
                
    except Exception as e:
        print(f"[ERROR] Error cleaning weekend data: {str(e)}")

# ----------------- DB upserts -----------------
def upsert_nav_daily(date, equity: Decimal, cash: Decimal, note="daily fetch"):
    with engine.begin() as conn:
        # First delete any existing record for this date
        conn.execute(
            text("DELETE FROM nav_weekly WHERE week_start_date = :date"),
            {"date": date}
        )
        # Then insert the new record
        conn.execute(
            text("""
            INSERT INTO nav_weekly (week_start_date, as_of_ts, equity, cash, note)
            VALUES (:date, NOW(), :equity, :cash, :note)
            """),
            {"date": date, "equity": equity, "cash": cash, "note": note},
        )

def upsert_benchmark_daily(date, px_date: dt.date, adj_close: Decimal, symbol="SPY"):
    with engine.begin() as conn:
        # First delete any existing record for this date and symbol
        conn.execute(
            text("DELETE FROM benchmark_weekly WHERE symbol = :sym AND week_start_date = :date"),
            {"sym": symbol, "date": date}
        )
        # Then insert the new record
        conn.execute(
            text("""
            INSERT INTO benchmark_weekly (symbol, week_start_date, px_date, adj_close)
            VALUES (:sym, :date, :pxd, :px)
            """),
            {"sym": symbol, "date": date, "pxd": px_date, "px": adj_close},
        )

def fetch(from_date):
    """
    Main fetch function that follows the standard pattern used by other fetch scripts.
    Fetches daily portfolio and benchmark data for the specified date range.
    """
    print(f"[INFO] Starting daily snapshots fetch from {from_date}...")
    
    # First, clean any existing weekend data that might contaminate p-values
    print("[INFO] Cleaning existing weekend data...")
    clean_weekend_data()
    
    # Parse from_date
    if isinstance(from_date, str):
        from_date = dt.datetime.strptime(from_date, "%Y-%m-%d").date()
    
    # Calculate days to fetch
    today = dt.date.today()
    days_to_fetch = (today - from_date).days + 1
    
    print(f"[INFO] Fetching {days_to_fetch} days of data...")
    
    # Fetch historical series
    alpaca_series = get_alpaca_equity_series(days_to_fetch)
    fmp_series = get_fmp_spy_adj_close(days_to_fetch)
    
    print(f"[INFO] Fetched {len(alpaca_series)} equity data points from Alpaca")
    print(f"[INFO] Fetched {len(fmp_series)} SPY data points from FMP")
    if alpaca_series:
        print(f"   Equity date range: {alpaca_series[0][0]} to {alpaca_series[-1][0]}")
    if fmp_series:
        print(f"   SPY date range: {fmp_series[0][0]} to {fmp_series[-1][0]}")

    # Build lookup dicts
    eq_by_day = dict(alpaca_series)  # {date: equity}
    px_by_day = dict(fmp_series)     # {date: adj_close}

    # Generate daily keys for the range
    daily_keys = daily_keys_between(from_date, today)
    
    upserts = 0
    for day in daily_keys:
        # Find the latest available data for this day or before
        # For equity: use the most recent equity value on or before this day
        equity_date = None
        for d in sorted(eq_by_day.keys(), reverse=True):  # Start from most recent
            if d <= day:
                equity_date = d
                break
        
        if equity_date is None:
            print(f"[WARNING] Skipping {day}: no equity data available.")
            continue

        # For benchmark: use the most recent price on or before this day
        price_date = None
        for d in sorted(px_by_day.keys(), reverse=True):  # Start from most recent
            if d <= day:
                price_date = d
                break
        
        if price_date is None:
            print(f"[WARNING] Skipping {day}: no SPY price data available.")
            continue

        # Store the data
        equity = eq_by_day[equity_date]
        cash = Decimal("0")  # Cash is not provided in history
        upsert_nav_daily(day, equity, cash, note=f"daily fetch as of {equity_date}")

        # Store benchmark data
        adj_close = px_by_day[price_date]
        upsert_benchmark_daily(day, price_date, adj_close, symbol="SPY")
        
        upserts += 1

    print(f"[OK] Daily snapshots fetch completed successfully - {upserts} records processed")
    return upserts

if __name__ == "__main__":
    try:
        # Default to last 30 days
        default_from_date = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        fetch(default_from_date)
        
        # Log successful execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_daily_snapshots.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_daily_snapshots.py", False, str(e))
        raise
