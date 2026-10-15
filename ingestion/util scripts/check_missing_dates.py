#!/usr/bin/env python3
"""
Check for missing dates in nav_weekly table
"""

import os
import psycopg2
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found")
    exit(1)

def check_missing_dates():
    """Check for missing dates in nav_weekly"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Get earliest and latest dates
                cur.execute("SELECT MIN(week_start_date), MAX(week_start_date) FROM nav_weekly")
                min_date, max_date = cur.fetchone()
                
                if not min_date or not max_date:
                    print("No data in nav_weekly table")
                    return
                
                print(f"Date range in nav_weekly: {min_date} to {max_date}")
                
                # Get all existing dates
                cur.execute("SELECT DISTINCT week_start_date FROM nav_weekly ORDER BY week_start_date")
                existing_dates = {row[0] for row in cur.fetchall()}
                
                # Find missing weekdays between min and today
                today = date.today()
                current = min_date
                missing_dates = []
                
                while current <= today:
                    # Only check weekdays
                    if current.weekday() < 5:  # Monday=0, Friday=4
                        if current not in existing_dates:
                            missing_dates.append(current)
                    current += timedelta(days=1)
                
                if missing_dates:
                    print(f"\nMissing dates: {len(missing_dates)}")
                    print(f"First missing: {missing_dates[0]}")
                    print(f"Last missing: {missing_dates[-1]}")
                    print(f"\nFirst 10 missing dates:")
                    for d in missing_dates[:10]:
                        print(f"  {d}")
                    if len(missing_dates) > 10:
                        print(f"  ... and {len(missing_dates) - 10} more")
                else:
                    print("\nNo missing dates found!")
                
                # Check specifically around January 1st
                jan_1 = date(2026, 1, 1)
                jan_dates = [jan_1 + timedelta(days=i) for i in range(10) if (jan_1 + timedelta(days=i)).weekday() < 5]
                print(f"\nChecking dates around January 1, 2026:")
                for d in jan_dates:
                    status = "EXISTS" if d in existing_dates else "MISSING"
                    print(f"  {d}: {status}")
                
                return missing_dates
                
    except psycopg2.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_missing_dates()
