"""
fix_data.py - Check and fix missing historical data in nav_weekly table

This script:
1. Checks the last updated date in nav_weekly
2. Calculates how many days need to be backfilled
3. Calls fill_daily_snapshots.py to backfill the missing data
"""
import os
import sys
import datetime as dt
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Import backfill function from fill_daily_snapshots
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fill_daily_snapshots import backfill, check_migration_status, clean_weekend_data

# Load environment variables
load_dotenv(override=True)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise SystemExit("Missing DATABASE_URL")

engine = create_engine(DB_URL, pool_pre_ping=True)

def get_last_updated_date():
    """Get the most recent date in nav_weekly table."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT MAX(week_start_date) 
            FROM nav_weekly
        """))
        
        last_date = result.scalar()
        return last_date

def fix_data():
    """
    Main function to check and fix missing data.
    Checks the last updated date and backfills from there to today.
    """
    print("🔍 Checking last updated date in nav_weekly...")
    
    # Check migration status first
    if not check_migration_status():
        print("\n❌ Cannot proceed without proper migration. Exiting.")
        return False
    
    # Get last updated date
    last_date = get_last_updated_date()
    today = dt.date.today()
    
    if last_date is None:
        print("⚠️  No data found in nav_weekly. Backfilling from 30 days ago...")
        backfill_days = 30
    else:
        # Calculate days between last date and today
        days_diff = (today - last_date).days
        print(f"📅 Last updated date: {last_date}")
        print(f"📅 Today: {today}")
        print(f"📊 Days since last update: {days_diff}")
        
        if days_diff <= 0:
            print("✅ Data is up to date! No backfill needed.")
            return True
        
        # Add a small buffer to ensure we get all data
        backfill_days = days_diff + 2
        print(f"🔄 Backfilling {backfill_days} days of data...")
    
    try:
        # Clean weekend data first
        print("🧹 Cleaning existing weekend data...")
        clean_weekend_data()
        
        # Call backfill from fill_daily_snapshots
        print(f"📥 Calling fill_daily_snapshots.backfill({backfill_days})...")
        backfill(backfill_days)
        
        print("\n✅ Backfill completed successfully!")
        
        # Verify the fix
        print("\n🔍 Verifying fix...")
        updated_last_date = get_last_updated_date()
        if updated_last_date:
            print(f"📅 Latest date in nav_weekly: {updated_last_date}")
            if updated_last_date >= today - dt.timedelta(days=1):
                print("✅ Data is now up to date!")
            else:
                print(f"⚠️  Latest date is still {today - updated_last_date} days behind today")
        else:
            print("⚠️  No data found after backfill")
        
        return True
            
    except Exception as e:
        print(f"❌ Error during backfill: {e}")
        raise

if __name__ == "__main__":
    try:
        success = fix_data()
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"❌ Script failed: {e}")
        sys.exit(1)

