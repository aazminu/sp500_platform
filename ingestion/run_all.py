import os
import sys
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
import importlib
from sqlalchemy import create_engine, text

"""
What it does: Runs all data fetching scripts in the correct order, with appropriate frequency checks and error handling.
How it  works: Loops through each script, checks if it should run based on frequency and last_run_date, calls the fetch function, and updates the last_run_date.
It also runs the run_trades script after all data fetching is complete.
Data storage: Updates the ingestion_metadata table with the last_run_date for each script.
"""

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv(override=True)
DATABASE_URL = os.getenv('DATABASE_URL')

# Map script names to their module names (without .py)
FETCH_MODULES = [
    ("fetch_tickers", "tickers"),
    ("fetch_prices", "prices"),
    ("fetch_historical_market_cap", "allocations"),
    ("fetch_metrics", "key_metrics"),
    ("fetch_profile", "profiles"),
    ("fetch_analyst_labels", "analyst_labels"),
    ("fetch_analyst_estimates", "analyst_estimates"),
    ("fetch_historical_analyst", "grades_historical"),
    ("fetch_stock_news", "stock_news"),
    ("fetch_weekly_llm", "weekly_llm_data"),  # New weekly LLM module
    ("fetch_daily_snapshots", "manual"),  # Daily portfolio and benchmark snapshots (manual - runs when run_all.py runs)
    ("run_trades", "actual_portfolio_allocations")  # Trading execution module
]

FREQUENCY_TO_DAYS = {
    "daily": 1,
    "weekly": 7,
    "quarterly": 90,
    "annual": 365,
    "manual": 0,  # always run if manual
}

engine = create_engine(DATABASE_URL)

def get_meta_info():
    with engine.connect() as conn:
        meta_info = {}
        for script, table in FETCH_MODULES:
            result = conn.execute(text("""
                SELECT frequency, last_run_date
                FROM ingestion_metadata
                WHERE script_name = :script
            """), {"script": f"{script}.py"})
            row = result.fetchone()
            if row:
                meta_info[script] = {
                    "frequency": row[0],
                    "last_run_date": row[1]
                }
                # Override frequency for manual scripts
                if table == "manual":
                    meta_info[script]["frequency"] = "manual"
            else:
                meta_info[script] = {
                    "frequency": "manual",
                    "last_run_date": (date.today() - timedelta(days=365*3)).isoformat()
                }
        return meta_info

def should_run_script(frequency, last_run_date):
    """Simple scheduling - you can add smart scheduling later"""
    if last_run_date is None:
        return True
    
    # Manual scripts always run
    if frequency == "manual":
        return True
    
    try:
        last_run = last_run_date if isinstance(last_run_date, date) else datetime.strptime(str(last_run_date), "%Y-%m-%d").date()
    except Exception:
        last_run = date.today() - timedelta(days=365*3)
    
    days_since = (date.today() - last_run).days
    
    if frequency == "daily":
        return days_since >= 1
    elif frequency == "weekly":
        return days_since >= 7
    elif frequency == "quarterly":
        return days_since >= 90
    elif frequency == "annual":
        return days_since >= 365
    else:
        return days_since >= 1

def update_last_run_date(script):
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE ingestion_metadata SET last_run_date = :today WHERE script_name = :script"),
            {"today": date.today().isoformat(), "script": f"{script}.py"}
        )
        conn.commit()

def get_last_nav_date():
    """Get the most recent date from nav_weekly table"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT MAX(week_start_date) 
                FROM nav_weekly
            """))
            row = result.fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return None

def run_weekly_stats_and_email():
    """Run weekly stats collection and email reporting using consolidated manager"""
    try:
        from weekly_stats_manager import run_weekly_stats_and_email
        run_weekly_stats_and_email()
    except Exception as e:
        print(f"[{datetime.now().isoformat()}]Error in weekly stats/email: {e}")

def main():
    print(f"\n[{datetime.now().isoformat()}] Starting the scheduled data fetching pipeline...\n")
    
    meta_info = get_meta_info()
    failed_orders = []
    
    # Run all the data fetching scripts first
    for script, _ in FETCH_MODULES[:-1]:  # Exclude run_trades for now
        freq = meta_info[script]["frequency"]
        last_run = meta_info[script]["last_run_date"]
        if should_run_script(freq, last_run):
            try:
                print(f"\n[{datetime.now().isoformat()}] --- Running {script}.py (frequency: {freq}, last_run_date: {last_run}) ---")
                module = importlib.import_module(script)
                # For manual scripts, use last known date from database or 7 days back
                if freq == "manual" and script == "fetch_daily_snapshots":
                    last_nav_date = get_last_nav_date()
                    if last_nav_date:
                        # Fetch from day after last known date (no cap so gaps self-heal)
                        from_date_obj = last_nav_date + timedelta(days=1)
                        from_date = from_date_obj.isoformat()
                        print(f"[{datetime.now().isoformat()}] Using last nav date: {last_nav_date}, fetching from: {from_date}")
                    else:
                        from_date = (date.today() - timedelta(days=30)).isoformat()
                        print(f"[{datetime.now().isoformat()}] No nav data found, fetching last 30 days")
                elif freq == "manual":
                    from_date = (date.today() - timedelta(days=7)).isoformat()
                else:
                    from_date = last_run if last_run else (date.today() - timedelta(days=365*3)).isoformat()
                print(f"[{datetime.now().isoformat()}] Calling fetch(from_date={from_date}) for {script}...")
                module.fetch(from_date)
                update_last_run_date(script)
                print(f"[{datetime.now().isoformat()}] --- {script}.py finished successfully and last_run_date updated ---")
            except Exception as e:
                print(f"[{datetime.now().isoformat()}] Error running {script}: {e}")
                continue
        else:
            print(f"[{datetime.now().isoformat()}] Skipping {script}.py (frequency: {freq}, last_run_date: {last_run}) - Not due yet.")
    
    # Always run run_trades if all data fetching succeeded
    try:
        print(f"\n[{datetime.now().isoformat()}] --- Running run_trades.py (always runs after data fetch) ---")
        module = importlib.import_module("run_trades")
        failed_orders = module.fetch()  # Capture failed orders
        print(f"[{datetime.now().isoformat()}] --- run_trades.py finished ---")
    except Exception as e:
        print(f"[{datetime.now().isoformat()}]  Error running run_trades: {e}")
    
    # Run weekly stats collection and email reporting
    run_weekly_stats_and_email()
    
    print(f"\n[{datetime.now().isoformat()}] --- Pipeline Execution Summary ---")
    print(f"[{datetime.now().isoformat()}]  All due fetch modules executed (or stopped on error).")
    
    # Display failed orders if any
    if failed_orders:
        print(f"\n[{datetime.now().isoformat()}]  FAILED ORDERS SUMMARY:")
        print(f"[{datetime.now().isoformat()}] Total failed orders: {len(failed_orders)}")
        for i, order in enumerate(failed_orders, 1):
            print(f"[{datetime.now().isoformat()}] {i}. {order['symbol']} {order['side'].upper()} ${order['notional']:.2f} - Error: {order['error']}")
        print(f"\n[{datetime.now().isoformat()}]   Please review and manually handle these failed orders.")
    else:
        print(f"[{datetime.now().isoformat()}]  No failed orders to report.")
    
    print()

if __name__ == "__main__":
    main()