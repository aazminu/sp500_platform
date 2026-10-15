#!/usr/bin/env python3
"""
Script to check data availability in nav_weekly table.
This helps diagnose why the history endpoint might be failing.
"""

import os
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables")
    exit(1)

def check_nav_data():
    """Check what data exists in nav_weekly table"""
    print("🔍 Checking nav_weekly table data availability...")
    print("=" * 80)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Check total records
                cur.execute("SELECT COUNT(*) FROM nav_weekly")
                total_count = cur.fetchone()[0]
                print(f"\n📊 Total records in nav_weekly: {total_count}")
                
                if total_count == 0:
                    print("\n❌ nav_weekly table is empty!")
                    print("\n💡 To populate data, run:")
                    print("   python 'ingestion/fetch_daily_snapshots.py'")
                    print("   or")
                    print("   python 'ingestion/util scripts/fill_daily_snapshots.py'")
                    return
                
                # Check date range
                cur.execute("""
                    SELECT MIN(week_start_date), MAX(week_start_date)
                    FROM nav_weekly
                """)
                min_date, max_date = cur.fetchone()
                print(f"📅 Date range: {min_date} to {max_date}")
                
                # Check YTD data specifically
                current_year = datetime.now().year
                ytd_start = datetime(current_year, 1, 1).date()
                today = datetime.now().date()
                
                cur.execute("""
                    SELECT COUNT(*), MIN(week_start_date), MAX(week_start_date)
                    FROM nav_weekly
                    WHERE week_start_date >= %s AND week_start_date <= %s
                """, (ytd_start, today))
                
                ytd_count, ytd_min, ytd_max = cur.fetchone()
                print(f"\n📈 YTD data (since {ytd_start}):")
                print(f"   Records: {ytd_count}")
                if ytd_count > 0:
                    print(f"   Date range: {ytd_min} to {ytd_max}")
                else:
                    print(f"   ❌ No YTD data found!")
                    print(f"\n💡 To backfill YTD data, run:")
                    print(f"   python 'ingestion/util scripts/fill_daily_snapshots.py'")
                
                # Check recent data
                seven_days_ago = today - timedelta(days=7)
                cur.execute("""
                    SELECT COUNT(*)
                    FROM nav_weekly
                    WHERE week_start_date >= %s
                """, (seven_days_ago,))
                recent_count = cur.fetchone()[0]
                print(f"\n📅 Recent data (last 7 days): {recent_count} records")
                
                # Show sample records
                print(f"\n📋 Sample records (last 5):")
                cur.execute("""
                    SELECT week_start_date, equity, cash, note
                    FROM nav_weekly
                    ORDER BY week_start_date DESC
                    LIMIT 5
                """)
                for row in cur.fetchall():
                    date, equity, cash, note = row
                    print(f"   {date}: equity=${equity:,.2f}, cash=${cash:,.2f}, note={note}")
                
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_nav_data()

