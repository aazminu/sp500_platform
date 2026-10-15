import os
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv(override=True)
DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(DATABASE_URL)

# Scripts to reset with their corresponding tables
SCRIPTS_AND_TABLES = [
    ("fetch_tickers.py", "tickers"),
    ("fetch_prices.py", "prices"), 
    ("fetch_historical_market_cap.py", "allocations"),
    ("fetch_metrics.py", "key_metrics"),
    ("fetch_profile.py", "profiles"),
    ("fetch_analyst_labels.py", "analyst_labels"),
    ("fetch_analyst_estimates.py", "analyst_estimates"),
    ("fetch_historical_analyst.py", "grades_historical"),
    ("fetch_stock_news.py", "stock_news"),
    ("fetch_weekly_llm.py", "weekly_llm_data"),
    ("run_trades.py", "actual_portfolio_allocations")
]

def reset_last_run_dates_and_clean_data():
    target_date = "2025-08-15"
    week_ago = (date.today() - timedelta(days=10)).isoformat()
    
    with engine.connect() as conn:
        for script, table in SCRIPTS_AND_TABLES:
            print(f"\nProcessing {script} -> {table}")
            
            # Reset last_run_date to 8/16/25
            conn.execute(
                text("UPDATE ingestion_metadata SET last_run_date = :target_date WHERE script_name = :script"),
                {"target_date": target_date, "script": script}
            )
            print(f"  ✅ Reset {script} last_run_date to {target_date}")
            
            # Remove last week of data based on table structure
            if table == "tickers":
                # tickers table doesn't have date columns, skip data cleanup
                print(f"  ⏭️  Skipping data cleanup for {table} (no date columns)")
            elif table == "prices":
                deleted = conn.execute(
                    text("DELETE FROM prices WHERE price_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (price_date >= {week_ago})")
            elif table == "allocations":
                deleted = conn.execute(
                    text("DELETE FROM allocations WHERE allocation_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (allocation_date >= {week_ago})")
            elif table == "key_metrics":
                deleted = conn.execute(
                    text("DELETE FROM key_metrics WHERE date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (date >= {week_ago})")
            elif table == "profiles":
                deleted = conn.execute(
                    text("DELETE FROM profiles WHERE date_fetched >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (date_fetched >= {week_ago})")
            elif table == "analyst_labels":
                deleted = conn.execute(
                    text("DELETE FROM analyst_labels WHERE label_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (label_date >= {week_ago})")
            elif table == "analyst_estimates":
                deleted = conn.execute(
                    text("DELETE FROM analyst_estimates WHERE report_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (report_date >= {week_ago})")
            elif table == "grades_historical":
                deleted = conn.execute(
                    text("DELETE FROM grades_historical WHERE rating_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (rating_date >= {week_ago})")
            elif table == "stock_news":
                deleted = conn.execute(
                    text("DELETE FROM stock_news WHERE published_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (published_date >= {week_ago})")
            elif table == "weekly_llm_data":
                deleted = conn.execute(
                    text("DELETE FROM weekly_llm_data WHERE created_at >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (created_at >= {week_ago})")
            elif table == "actual_portfolio_allocations":
                deleted = conn.execute(
                    text("DELETE FROM actual_portfolio_allocations WHERE allocation_date >= :week_ago"),
                    {"week_ago": week_ago}
                ).rowcount
                print(f"  🗑️  Deleted {deleted} rows from {table} (allocation_date >= {week_ago})")
        
        conn.commit()
        print(f"\n✅ All last_run_dates reset to {target_date} and last week of data cleaned!")

if __name__ == "__main__":
    reset_last_run_dates_and_clean_data()
