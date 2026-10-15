#!/usr/bin/env python3
"""
Rebuild weekly stats data using fill weekly snapshots
This script will:
1. Clear existing weekly_stats data
2. Run the fill weekly snapshots to rebuild the data
"""

import os
import sys
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load .env from current directory
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Missing DATABASE_URL")

def clear_weekly_stats():
    """Clear all existing weekly_stats data"""
    print("🗑️  Clearing existing weekly_stats data...")
    
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # Clear all weekly_stats data
        result = conn.execute(text("DELETE FROM weekly_stats"))
        conn.commit()
        print(f"✅ Cleared {result.rowcount} rows from weekly_stats")
    
    return True

def rebuild_weekly_snapshots(backfill_days=30):
    """Rebuild weekly snapshots data"""
    print(f"🔄 Rebuilding weekly snapshots with {backfill_days} days backfill...")
    
    try:
        # Import and run the fill weekly snapshots
        from fill_weekly_snapshots import main as run_weekly_snapshots
        success = run_weekly_snapshots(backfill_days)
        
        if success:
            print("✅ Weekly snapshots rebuilt successfully")
            return True
        else:
            print("❌ Weekly snapshots rebuild failed")
            return False
            
    except Exception as e:
        print(f"❌ Error rebuilding weekly snapshots: {str(e)}")
        return False

def verify_data():
    """Verify the rebuilt data"""
    print("🔍 Verifying rebuilt data...")
    
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # Check how many records we have
        count_result = conn.execute(text("SELECT COUNT(*) FROM weekly_stats")).fetchone()
        record_count = count_result[0] if count_result else 0
        
        # Check for records with benchmark data
        benchmark_count = conn.execute(text("""
            SELECT COUNT(*) FROM weekly_stats 
            WHERE benchmark_return_pct IS NOT NULL 
            AND excess_return_pct IS NOT NULL
        """)).fetchone()
        benchmark_records = benchmark_count[0] if benchmark_count else 0
        
        # Get date range
        date_range = conn.execute(text("""
            SELECT MIN(week_start_date), MAX(week_start_date) 
            FROM weekly_stats
        """)).fetchone()
        
        print(f"📊 Data verification results:")
        print(f"   Total records: {record_count}")
        print(f"   Records with benchmark data: {benchmark_records}")
        if date_range and date_range[0]:
            print(f"   Date range: {date_range[0]} to {date_range[1]}")
        
        return record_count > 0

def main():
    print("=" * 60)
    print("🔄 Weekly Stats Rebuild Script")
    print("=" * 60)
    
    print("⚠️  This will:")
    print("   1. DELETE all existing weekly_stats data")
    print("   2. Rebuild the data using fill weekly snapshots")
    print("   3. This is IRREVERSIBLE!")
    print()
    
    response = input("🤔 Do you want to proceed? (y/N): ").strip().lower()
    
    if response not in ['y', 'yes']:
        print("❌ Rebuild cancelled by user")
        return
    
    try:
        # Step 1: Clear existing data
        if not clear_weekly_stats():
            print("❌ Failed to clear existing data")
            return
        
        # Step 2: Rebuild with weekly snapshots
        if not rebuild_weekly_snapshots(30):  # 30 days backfill
            print("❌ Failed to rebuild weekly snapshots")
            return
        
        # Step 3: Verify the data
        if not verify_data():
            print("❌ Data verification failed")
            return
        
        print("\n🎉 Weekly stats rebuild completed successfully!")
        print("📊 Your weekly_stats table now has fresh data with benchmark information")
        
    except Exception as e:
        print(f"❌ Rebuild failed: {str(e)}")
        return

if __name__ == "__main__":
    main()
