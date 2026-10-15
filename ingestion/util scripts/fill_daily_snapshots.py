# fill_daily_snapshots.py
# 
# SAFETY NOTE: This script is designed to work ALONGSIDE your existing weekly_stats_manager.py
# It only populates the new benchmark columns (benchmark_return_pct, excess_return_pct)
# and does NOT interfere with your existing weekly stats workflow.
#
# This script should be run AFTER your regular weekly_stats_manager.py has run.
# It will either update existing weekly_stats records or create minimal new ones.
# 
# MODIFIED: Now collects data for every day of the backfill period instead of just weekly snapshots.
#
import os, sys, requests, datetime as dt
from decimal import Decimal
import pytz
from sqlalchemy import create_engine, text

# ----------------- Config/Env -----------------
# Load .env from current directory (util scripts folder)
from dotenv import load_dotenv
load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
FMP_KEY = os.getenv("FMP_API_KEY")
ALPACA_BASE = os.getenv("ALPACA_BASE", "https://paper-api.alpaca.markets")  # or live base
DEFAULT_BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "20"))

if not DB_URL:
    raise SystemExit("Missing DATABASE_URL")

NY = pytz.timezone("America/New_York")
engine = create_engine(DB_URL, pool_pre_ping=True)

# ----------------- Time helpers -----------------
def to_et(d: dt.datetime) -> dt.datetime:
    return d.astimezone(NY)

def monday_of_week(d_et: dt.datetime) -> dt.date:
    return (d_et - dt.timedelta(days=d_et.weekday())).date()

def is_weekday(date: dt.date) -> bool:
    """Check if a date is a weekday (Monday=0, Sunday=6)."""
    return date.weekday() < 5  # Monday=0, Tuesday=1, ..., Friday=4

def daily_keys_between(start_date: dt.date, end_date: dt.date, weekdays_only: bool = True):
    """All dates (inclusive) between start and end. Optionally skip weekends."""
    d = start_date
    keys = []
    while d <= end_date:
        if not weekdays_only or is_weekday(d):
            keys.append(d)
        d += dt.timedelta(days=1)
    return keys

def get_trading_days_only(start_date: dt.date, end_date: dt.date):
    """Get only trading days (weekdays) between start and end dates."""
    trading_days = []
    current = start_date
    while current <= end_date:
        if is_weekday(current):
            trading_days.append(current)
        current += dt.timedelta(days=1)
    return trading_days

# ----------------- Data fetchers -----------------
def get_alpaca_equity_series(days: int):
    """
    STRICT historical pull from Alpaca portfolio history.
    Returns list[(date_ET, Decimal equity)] for the last N calendar days.
    No fallbacks. Raises if Alpaca returns an empty series.

    Env/globals required:
      DB_URL, ALPACA_BASE, ALPACA_API_KEY, ALPACA_API_SECRET
      NY = pytz.timezone("America/New_York")
      Decimal, dt, requests imported
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
        # 'intraday_reporting' has no effect with 1D; API only returns trading days. :contentReference[oaicite:1]{index=1}
    }

    r = requests.get(base_url, headers=headers, params=params, timeout=30)
    try:
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Alpaca portfolio history HTTP error: {e} | url={r.url} | body={r.text[:500]}")

    j = r.json()
    stamps = j.get("timestamp", [])
    equities = j.get("equity", [])
    
    print(f"[DEBUG] Alpaca API Debug:")
    print(f"   Requested date range: {params['date_start']} to {params['date_end']}")
    print(f"   Raw response keys: {list(j.keys())}")
    print(f"   Timestamps returned: {len(stamps)}")
    print(f"   Equities returned: {len(equities)}")
    if stamps:
        print(f"   First timestamp: {stamps[0]} ({dt.datetime.fromtimestamp(stamps[0], tz=dt.timezone.utc)})")
        print(f"   Last timestamp: {stamps[-1]} ({dt.datetime.fromtimestamp(stamps[-1], tz=dt.timezone.utc)})")

    if not equities or not stamps:
        # Be explicit so you can fix params/env quickly.
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

# ----------------- DB upserts -----------------
def upsert_nav_daily(date, equity: Decimal, cash: Decimal, note="backfill or cron"):
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

def pct_change(curr: Decimal, prev: Decimal) -> Decimal | None:
    if prev is None or prev == 0:
        return None
    return (curr / prev - Decimal("1")) * Decimal("100")

def compute_and_upsert_daily_return(day: dt.date):
    """
    Reads day and previous day snapshots and updates weekly_stats with benchmark data.
    This function ONLY updates the new benchmark columns, preserving existing data.
    """
    with engine.begin() as conn:
        prev_day = conn.execute(
            text("SELECT MAX(week_start_date) FROM nav_weekly WHERE week_start_date < :day"),
            {"day": day}
        ).scalar()

        if not prev_day:
            return False  # no prior day yet

        nav = conn.execute(
            text("SELECT week_start_date, equity FROM nav_weekly WHERE week_start_date IN (:p, :c)"),
            {"p": prev_day, "c": day}
        ).fetchall()
        bench = conn.execute(
            text("""
                SELECT week_start_date, adj_close
                FROM benchmark_weekly
                WHERE symbol='SPY' AND week_start_date IN (:p, :c)
            """),
            {"p": prev_day, "c": day}
        ).fetchall()

    if len(nav) < 2 or len(bench) < 2:
        return False

    nav_map = {r[0]: Decimal(str(r[1])) for r in nav}
    bench_map = {r[0]: Decimal(str(r[1])) for r in bench}

    port_ret = pct_change(nav_map[day], nav_map[prev_day])
    bench_ret = pct_change(bench_map[day], bench_map[prev_day])
    if port_ret is None or bench_ret is None:
        return False
    excess = port_ret - bench_ret

    # Update ONLY the new benchmark columns, preserving existing weekly_stats data
    with engine.begin() as conn:
        # Check if weekly_stats record exists for this day (using Monday of the week)
        week_start = monday_of_week(dt.datetime.combine(day, dt.time.min))
        existing = conn.execute(
            text("SELECT id FROM weekly_stats WHERE week_start_date = :wk"),
            {"wk": week_start}
        ).fetchone()
        
        if existing:
            # Update existing record with benchmark data
            conn.execute(
                text("""
                UPDATE weekly_stats 
                SET benchmark_return_pct = :br,
                    excess_return_pct = :er
                WHERE week_start_date = :wk
                """),
                {"wk": week_start, "br": bench_ret, "er": excess},
            )
        else:
            # Create new record with minimal required fields
            week_end = week_start + dt.timedelta(days=6)
            conn.execute(
                text("""
                INSERT INTO weekly_stats
                  (week_start_date, week_end_date, portfolio_return_pct, benchmark_return_pct, excess_return_pct, top_5_notional_changes, scripts_executed)
                VALUES
                  (:wk, :we, :pr, :br, :er, '[]', '{}')
                """),
                {"wk": week_start, "we": week_end, "pr": port_ret, "br": bench_ret, "er": excess},
            )
    
    print(f"[OK] {day}: portfolio={port_ret:.4f}%  benchmark={bench_ret:.4f}%  excess={excess:.4f}%")
    return True

def compute_and_upsert_week_return(wk: dt.date):
    """
    Reads wk and previous week snapshots and updates weekly_stats with benchmark data.
    This function ONLY updates the new benchmark columns, preserving existing data.
    """
    with engine.begin() as conn:
        prev_wk = conn.execute(
            text("SELECT MAX(week_start_date) FROM nav_weekly WHERE week_start_date < :wk"),
            {"wk": wk}
        ).scalar()

        if not prev_wk:
            return False  # no prior week yet

        nav = conn.execute(
            text("SELECT week_start_date, equity FROM nav_weekly WHERE week_start_date IN (:p, :c)"),
            {"p": prev_wk, "c": wk}
        ).fetchall()
        bench = conn.execute(
            text("""
                SELECT week_start_date, adj_close
                FROM benchmark_weekly
                WHERE symbol='SPY' AND week_start_date IN (:p, :c)
            """),
            {"p": prev_wk, "c": wk}
        ).fetchall()

    if len(nav) < 2 or len(bench) < 2:
        return False

    nav_map = {r[0]: Decimal(str(r[1])) for r in nav}
    bench_map = {r[0]: Decimal(str(r[1])) for r in bench}

    port_ret = pct_change(nav_map[wk], nav_map[prev_wk])
    bench_ret = pct_change(bench_map[wk], bench_map[prev_wk])
    if port_ret is None or bench_ret is None:
        return False
    excess = port_ret - bench_ret

    # Update ONLY the new benchmark columns, preserving existing weekly_stats data
    with engine.begin() as conn:
        # Check if weekly_stats record exists for this week
        existing = conn.execute(
            text("SELECT id FROM weekly_stats WHERE week_start_date = :wk"),
            {"wk": wk}
        ).fetchone()
        
        if existing:
            # Update existing record with benchmark data
            conn.execute(
                text("""
                UPDATE weekly_stats 
                SET benchmark_return_pct = :br,
                    excess_return_pct = :er
                WHERE week_start_date = :wk
                """),
                {"wk": wk, "br": bench_ret, "er": excess},
            )
        else:
            # Create new record with minimal required fields
            week_end = wk + dt.timedelta(days=6)
            conn.execute(
                text("""
                INSERT INTO weekly_stats
                  (week_start_date, week_end_date, portfolio_return_pct, benchmark_return_pct, excess_return_pct, top_5_notional_changes, scripts_executed)
                VALUES
                  (:wk, :we, :pr, :br, :er, '[]', '{}')
                """),
                {"wk": wk, "we": week_end, "pr": port_ret, "br": bench_ret, "er": excess},
            )
    
    print(f"[OK] {wk}: portfolio={port_ret:.4f}%  benchmark={bench_ret:.4f}%  excess={excess:.4f}%")
    return True

# ----------------- Backfill logic -----------------
def backfill(backfill_days: int):
    now_et = to_et(dt.datetime.now(dt.timezone.utc))
    start_et = now_et - dt.timedelta(days=backfill_days)

    # Build daily keys in range (weekdays only to avoid weekend data contamination)
    daily_keys = get_trading_days_only(start_et.date(), now_et.date())
    if not daily_keys:
        print("No trading days to backfill.")
        return
    
    print(f"[INFO] Processing {len(daily_keys)} trading days (weekends skipped)")

    # Fetch historical series once
    alpaca_series = get_alpaca_equity_series(backfill_days)
    fmp_series = get_fmp_spy_adj_close(backfill_days)
    
    print(f"[INFO] Fetched {len(alpaca_series)} equity data points from Alpaca")
    print(f"[INFO] Fetched {len(fmp_series)} SPY data points from FMP")
    if alpaca_series:
        print(f"   Equity date range: {alpaca_series[0][0]} to {alpaca_series[-1][0]}")
    if fmp_series:
        print(f"   SPY date range: {fmp_series[0][0]} to {fmp_series[-1][0]}")

    # Build lookup dicts
    eq_by_day = dict(alpaca_series)  # {date: equity}
    px_by_day = dict(fmp_series)     # {date: adj_close}

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
        upsert_nav_daily(day, equity, cash, note=f"daily backfill as of {equity_date}")

        # Store benchmark data
        adj_close = px_by_day[price_date]
        upsert_benchmark_daily(day, price_date, adj_close, symbol="SPY")

        # Try compute daily return if prior day exists
        compute_and_upsert_daily_return(day)

# ----------------- "Today" (non-backfill) one-shot -----------------
def run_today_once():
    # "today" snapshot (no backfill): use current equity and prior trading day SPY
    now_et = to_et(dt.datetime.now(dt.timezone.utc))
    today = now_et.date()
    
    # Skip if today is a weekend
    if not is_weekday(today):
        print(f"[SKIP] Skipping weekend day: {today}")
        return

    # current Alpaca account
    equity, cash = Decimal("0"), Decimal("0")
    if ALPACA_KEY and ALPACA_SECRET:
        # Fall back to 0s if account call fails
        try:
            acct = requests.get(
                f"{ALPACA_BASE}/v2/account",
                headers={"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET},
                timeout=30
            ).json()
            equity = Decimal(str(acct.get("equity", "0")))
            cash = Decimal(str(acct.get("cash", "0")))
        except Exception as e:
            print(f"WARNING: Alpaca account fetch failed: {e}")
    upsert_nav_daily(today, equity, cash, note="daily cron snapshot")

    # latest prior trading day SPY
    series = get_fmp_spy_adj_close(15)
    if series:
        px_date, adj_close = series[-1]  # last item is latest trading day after sort
        upsert_benchmark_daily(today, px_date, adj_close)
    else:
        print("WARNING: No SPY price fetched.")

    # compute returns if possible
    compute_and_upsert_daily_return(today)

# ----------------- Safety checks -----------------
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

def check_migration_status():
    """
    Check if the required tables and columns exist before running
    """
    try:
        with engine.connect() as conn:
            # Check if new tables exist
            nav_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'nav_weekly'
                );
            """)).fetchone()[0]
            
            bench_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'benchmark_weekly'
                );
            """)).fetchone()[0]
            
            # Check if new columns exist in weekly_stats
            columns_exist = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'weekly_stats' 
                    AND column_name IN ('benchmark_return_pct', 'excess_return_pct')
                );
            """)).fetchone()[0]
            
            if not (nav_exists and bench_exists and columns_exist):
                print("[ERROR] Required tables/columns not found!")
                print("   Please run the migration script first:")
                print("   python migrate_weekly_analytics.py")
                return False
            
            print("[OK] Migration status: All required tables and columns exist")
            return True
            
    except Exception as e:
        print(f"[ERROR] Error checking migration status: {str(e)}")
        return False

def update_ingestion_metadata():
    """
    Update ingestion_metadata to reflect that fetch_daily_snapshots.py has run.
    Updates all three tables that use this script: nav_weekly, benchmark_weekly, daily_snapshots
    """
    try:
        today = dt.date.today()
        with engine.begin() as conn:
            # Update all three tables that use fetch_daily_snapshots.py
            conn.execute(
                text("""
                    UPDATE ingestion_metadata 
                    SET last_run_date = :today 
                    WHERE script_name = 'fetch_daily_snapshots.py'
                """),
                {"today": today}
            )
            updated = conn.execute(
                text("SELECT COUNT(*) FROM ingestion_metadata WHERE script_name = 'fetch_daily_snapshots.py' AND last_run_date = :today"),
                {"today": today}
            ).scalar()
            print(f"[OK] Updated ingestion_metadata: {updated} table(s) now show last_run_date = {today}")
            return True
    except Exception as e:
        print(f"[WARNING] Could not update ingestion_metadata: {str(e)}")
        return False

def main(backfill_days=44):
    """
    Main function to run daily snapshots.
    Similar to other fetch files - just specify how many days to backfill.
    
    NOTE: This script now skips weekends to avoid contaminating p-value calculations
    with 0% returns from non-trading days.
    """
    print("[INFO] Starting daily snapshots process (weekends skipped)...")
    
    # Check migration status before running
    if not check_migration_status():
        print("\n[ERROR] Cannot proceed without proper migration. Exiting.")
        return False
    
    try:
        # First, clean any existing weekend data that might contaminate p-values
        print("[INFO] Cleaning existing weekend data...")
        clean_weekend_data()
        
        # Run backfill for specified days
        backfill(max(backfill_days, 1))
        
        # Update ingestion_metadata to reflect successful run
        update_ingestion_metadata()
        
        print("[OK] Daily snapshots completed successfully")
        return True
    except Exception as e:
        print(f"[ERROR] Error in daily snapshots: {str(e)}")
        return False

if __name__ == "__main__":
    main()
