#!/usr/bin/env python3
"""
Script to verify that only trading days are being used for p-value calculations.
This helps ensure weekend data contamination is eliminated.
"""

import os
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables")
    exit(1)

def check_trading_days_data():
    """
    Check if the data contains only trading days (no weekends).
    """
    print("🔍 Verifying trading days data...")
    print("=" * 80)

    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Check nav_weekly data
                cur.execute("""
                    SELECT week_start_date, 
                           EXTRACT(DOW FROM week_start_date) as day_of_week,
                           COUNT(*) as count
                    FROM nav_weekly 
                    WHERE week_start_date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY week_start_date, EXTRACT(DOW FROM week_start_date)
                    ORDER BY week_start_date;
                """)
                nav_data = cur.fetchall()
                
                print(f"\n📊 NAV Weekly Data (last 30 days):")
                print(f"   Total records: {len(nav_data)}")
                
                weekend_count = 0
                weekday_count = 0
                for date, dow, count in nav_data:
                    day_name = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][int(dow)]
                    if dow in [0, 6]:  # Sunday=0, Saturday=6
                        weekend_count += count
                        print(f"   ⚠️  {date} ({day_name}) - {count} records")
                    else:
                        weekday_count += count
                        print(f"   ✅ {date} ({day_name}) - {count} records")
                
                print(f"\n   Summary: {weekday_count} weekday records, {weekend_count} weekend records")
                
                # Check benchmark_weekly data
                cur.execute("""
                    SELECT week_start_date, 
                           EXTRACT(DOW FROM week_start_date) as day_of_week,
                           COUNT(*) as count
                    FROM benchmark_weekly 
                    WHERE week_start_date >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY week_start_date, EXTRACT(DOW FROM week_start_date)
                    ORDER BY week_start_date;
                """)
                bench_data = cur.fetchall()
                
                print(f"\n📈 Benchmark Weekly Data (last 30 days):")
                print(f"   Total records: {len(bench_data)}")
                
                bench_weekend_count = 0
                bench_weekday_count = 0
                for date, dow, count in bench_data:
                    day_name = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][int(dow)]
                    if dow in [0, 6]:  # Sunday=0, Saturday=6
                        bench_weekend_count += count
                        print(f"   ⚠️  {date} ({day_name}) - {count} records")
                    else:
                        bench_weekday_count += count
                        print(f"   ✅ {date} ({day_name}) - {count} records")
                
                print(f"\n   Summary: {bench_weekday_count} weekday records, {bench_weekend_count} weekend records")
                
                # Check for zero returns that might indicate weekend contamination
                cur.execute("""
                    SELECT COUNT(*) as zero_return_count
                    FROM nav_weekly n1
                    JOIN nav_weekly n2 ON n2.week_start_date = n1.week_start_date + INTERVAL '1 day'
                    WHERE n1.week_start_date >= CURRENT_DATE - INTERVAL '30 days'
                    AND n1.equity = n2.equity
                """)
                zero_returns = cur.fetchone()[0]
                
                print(f"\n🔍 Zero Return Analysis:")
                print(f"   Consecutive days with identical equity: {zero_returns}")
                
                if weekend_count > 0 or bench_weekend_count > 0:
                    print(f"\n❌ WARNING: Weekend data found! This will contaminate p-value calculations.")
                    print(f"   Run the clean_weekend_data() function in fill_daily_snapshots.py")
                elif zero_returns > 0:
                    print(f"\n⚠️  WARNING: {zero_returns} consecutive days with identical equity values.")
                    print(f"   This might indicate weekend data contamination.")
                else:
                    print(f"\n✅ GOOD: Only trading days found in the data.")
                    print(f"   P-value calculations should be clean.")

    except Exception as e:
        print(f"❌ Error checking trading days data: {e}")

if __name__ == "__main__":
    check_trading_days_data()
