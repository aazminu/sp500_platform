#!/usr/bin/env python3
"""
Check last run dates for all tables in ingestion_metadata
This will show when each data collection script last ran
"""

import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables")
    exit(1)

def check_last_run_dates():
    """Check last run dates for all tables"""
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                print("🔍 Checking last run dates for all tables...")
                print("=" * 80)
                
                # Get all metadata
                cur.execute("""
                    SELECT 
                        table_name,
                        frequency,
                        script_name,
                        last_run_date,
                        smart_boundary,
                        boundary_days,
                        sp500_tracked,
                        last_sp500_check
                    FROM ingestion_metadata 
                    ORDER BY table_name
                """)
                
                metadata = cur.fetchall()
                
                if not metadata:
                    print("❌ No metadata found in ingestion_metadata table")
                    return
                
                print(f"{'Table Name':<25} {'Frequency':<10} {'Script':<25} {'Last Run':<12} {'Days Ago':<8}")
                print("-" * 80)
                
                today = datetime.now().date()
                
                for row in metadata:
                    table_name, frequency, script_name, last_run_date, smart_boundary, boundary_days, sp500_tracked, last_sp500_check = row
                    
                    # Calculate days since last run
                    if last_run_date:
                        days_ago = (today - last_run_date).days
                        days_str = f"{days_ago}d ago"
                        
                        # Color coding based on how old the data is
                        if days_ago == 0:
                            status = "🟢"
                        elif days_ago <= 1:
                            status = "🟡"
                        elif days_ago <= 7:
                            status = "🟠"
                        else:
                            status = "🔴"
                    else:
                        days_str = "Never"
                        status = "🔴"
                    
                    print(f"{status} {table_name:<23} {frequency:<10} {script_name or 'N/A':<23} {str(last_run_date) or 'Never':<12} {days_str:<8}")
                
                print("-" * 80)
                
                # Summary
                print(f"\n📊 Summary:")
                print(f"Total tables: {len(metadata)}")
                
                # Count by status
                recent_count = sum(1 for row in metadata if row[3] and (today - row[3]).days <= 1)
                old_count = sum(1 for row in metadata if row[3] and (today - row[3]).days > 7)
                never_count = sum(1 for row in metadata if not row[3])
                
                print(f"🟢 Recent (≤1 day): {recent_count}")
                print(f"🟠 Old (>7 days): {old_count}")
                print(f"🔴 Never run: {never_count}")
                
                # Check specific daily tables
                print(f"\n🔍 Daily snapshot tables:")
                daily_tables = [row for row in metadata if row[1] == 'daily']
                
                for table_name, frequency, script_name, last_run_date, smart_boundary, boundary_days, sp500_tracked, last_sp500_check in daily_tables:
                    if last_run_date:
                        days_ago = (today - last_run_date).days
                        if days_ago > 1:
                            print(f"  ⚠️  {table_name}: {days_ago} days ago (script: {script_name})")
                        else:
                            print(f"  ✅ {table_name}: {days_ago} days ago (script: {script_name})")
                    else:
                        print(f"  ❌ {table_name}: Never run (script: {script_name})")
                
                # Check nav_weekly specifically
                print(f"\n📈 nav_weekly table status:")
                cur.execute("SELECT COUNT(*), MAX(week_start_date) FROM nav_weekly")
                nav_count, nav_latest = cur.fetchone()
                
                if nav_count > 0:
                    days_since_nav = (today - nav_latest).days
                    print(f"  Records: {nav_count}")
                    print(f"  Latest date: {nav_latest}")
                    print(f"  Days since latest: {days_since_nav}")
                    
                    if days_since_nav > 1:
                        print(f"  ⚠️  nav_weekly data is {days_since_nav} days old")
                    else:
                        print(f"  ✅ nav_weekly is up to date")
                else:
                    print(f"  ❌ nav_weekly table is empty")
                
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("📅 Checking last run dates for all data collection scripts")
    print("=" * 60)
    check_last_run_dates()
    print("=" * 60)
    print("✅ Check completed")
