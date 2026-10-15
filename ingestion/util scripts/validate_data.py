import os
import sys
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables

load_dotenv(override=True)
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL)

def validate_llm_data():
    """
    Validate that there's sufficient data for the LLM script to process tickers
    """
    print("🔍 Validating data availability for LLM script...")
    
    with engine.connect() as conn:
        # Check 1: Total tickers in database
        result = conn.execute(text("SELECT COUNT(*) FROM tickers"))
        total_tickers = result.fetchone()[0]
        print(f"📊 Total tickers in database: {total_tickers}")
        
        # Check 2: Tickers with prices
        result = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM prices"))
        tickers_with_prices = result.fetchone()[0]
        print(f"📈 Tickers with price data: {tickers_with_prices}")
        
        # Check 3: Tickers with allocations
        result = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM allocations"))
        tickers_with_allocations = result.fetchone()[0]
        print(f"💰 Tickers with allocation data: {tickers_with_allocations}")
        
        # Check 4: Tickers with profiles
        result = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM profiles"))
        tickers_with_profiles = result.fetchone()[0]
        print(f"📋 Tickers with profile data: {tickers_with_profiles}")
        
        # Check 5: Tickers that meet LLM requirements (same query as fetch_weekly_llm.py)
        result = conn.execute(text("""
            SELECT COUNT(DISTINCT t.ticker) 
            FROM tickers t
            WHERE t.ticker IN (
                SELECT DISTINCT ticker FROM prices 
                WHERE ticker IN (SELECT DISTINCT ticker FROM allocations)
                AND ticker IN (SELECT DISTINCT ticker FROM profiles)
            )
        """))
        tickers_for_llm = result.fetchone()[0]
        print(f"🤖 Tickers ready for LLM processing: {tickers_for_llm}")
        
        # Check 6: Sample of tickers that would be processed
        if tickers_for_llm > 0:
            result = conn.execute(text("""
                SELECT DISTINCT t.ticker 
                FROM tickers t
                WHERE t.ticker IN (
                    SELECT DISTINCT ticker FROM prices 
                    WHERE ticker IN (SELECT DISTINCT ticker FROM allocations)
                    AND ticker IN (SELECT DISTINCT ticker FROM profiles)
                )
                ORDER BY t.ticker 
                LIMIT 10
            """))
            sample_tickers = [row[0] for row in result.fetchall()]
            print(f"📝 Sample tickers that would be processed: {sample_tickers}")
        else:
            print("❌ No tickers meet the LLM requirements!")
            
            # Check what's missing for a few sample tickers
            result = conn.execute(text("""
                SELECT DISTINCT t.ticker 
                FROM tickers t
                LIMIT 5
            """))
            sample_tickers = [row[0] for row in result.fetchall()]
            
            print(f"\n🔍 Checking requirements for sample tickers: {sample_tickers}")
            for ticker in sample_tickers:
                has_prices = conn.execute(text("SELECT COUNT(*) FROM prices WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()[0]
                has_allocations = conn.execute(text("SELECT COUNT(*) FROM allocations WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()[0]
                has_profiles = conn.execute(text("SELECT COUNT(*) FROM profiles WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()[0]
                
                print(f"  {ticker}: prices={has_prices}, allocations={has_allocations}, profiles={has_profiles}")
        
        # Check 6b: Comprehensive ticker validation
        print(f"\n🔍 COMPREHENSIVE TICKER VALIDATION:")
        
        # Get all tickers and check their data completeness
        result = conn.execute(text("SELECT ticker FROM tickers ORDER BY ticker"))
        all_tickers = [row[0] for row in result.fetchall()]
        
        tickers_with_all_data = 0
        tickers_missing_profiles = 0
        tickers_missing_allocations = 0
        tickers_missing_prices = 0
        
        print(f"   Checking {len(all_tickers)} tickers for data completeness...")
        
        for ticker in all_tickers:
            has_prices = conn.execute(text("SELECT COUNT(*) FROM prices WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()[0]
            has_allocations = conn.execute(text("SELECT COUNT(*) FROM allocations WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()[0]
            has_profiles = conn.execute(text("SELECT COUNT(*) FROM profiles WHERE ticker = :ticker"), {"ticker": ticker}).fetchone()[0]
            
            if has_prices > 0 and has_allocations > 0 and has_profiles > 0:
                tickers_with_all_data += 1
            else:
                if has_profiles == 0:
                    tickers_missing_profiles += 1
                if has_allocations == 0:
                    tickers_missing_allocations += 1
                if has_prices == 0:
                    tickers_missing_prices += 1
        
        print(f"   ✅ Tickers with ALL required data: {tickers_with_all_data}")
        print(f"   ❌ Tickers missing profiles: {tickers_missing_profiles}")
        print(f"   ❌ Tickers missing allocations: {tickers_missing_allocations}")
        print(f"   ❌ Tickers missing prices: {tickers_missing_prices}")
        
        # Show first 10 tickers missing profiles (most likely issue)
        if tickers_missing_profiles > 0:
            result = conn.execute(text("""
                SELECT t.ticker 
                FROM tickers t
                WHERE NOT EXISTS (SELECT 1 FROM profiles p WHERE p.ticker = t.ticker)
                ORDER BY t.ticker
                LIMIT 10
            """))
            missing_profiles = [row[0] for row in result.fetchall()]
            print(f"   📝 Sample tickers missing profiles: {missing_profiles}")
        
        # Show first 10 tickers missing allocations
        if tickers_missing_allocations > 0:
            result = conn.execute(text("""
                SELECT t.ticker 
                FROM tickers t
                WHERE NOT EXISTS (SELECT 1 FROM allocations a WHERE a.ticker = t.ticker)
                ORDER BY t.ticker
                LIMIT 10
            """))
            missing_allocations = [row[0] for row in result.fetchall()]
            print(f"   📝 Sample tickers missing allocations: {missing_allocations}")
        
        # Show first 10 tickers missing prices
        if tickers_missing_prices > 0:
            result = conn.execute(text("""
                SELECT t.ticker 
                FROM tickers t
                WHERE NOT EXISTS (SELECT 1 FROM prices p WHERE p.ticker = t.ticker)
                ORDER BY t.ticker
                LIMIT 10
            """))
            missing_prices = [row[0] for row in result.fetchall()]
            print(f"   📝 Sample tickers missing prices: {missing_prices}")
        
        # Check 7: Recent data availability
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        
        result = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM prices WHERE price_date >= :week_ago"), {"week_ago": week_ago})
        recent_prices = result.fetchone()[0]
        print(f"📅 Tickers with recent price data (last 7 days): {recent_prices}")
        
        result = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM allocations WHERE allocation_date >= :week_ago"), {"week_ago": week_ago})
        recent_allocations = result.fetchone()[0]
        print(f"📅 Tickers with recent allocation data (last 7 days): {recent_allocations}")
        
        result = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM profiles WHERE date_fetched >= :week_ago"), {"week_ago": week_ago})
        recent_profiles = result.fetchone()[0]
        print(f"📅 Tickers with recent profile data (last 7 days): {recent_profiles}")
        
        # Check 8: Script last run dates
        print(f"\n🕒 SCRIPT LAST RUN DATES:")
        scripts_to_check = [
            ("fetch_profile.py", "profiles"),
            ("fetch_prices.py", "prices"), 
            ("fetch_historical_market_cap.py", "allocations"),
            ("fetch_weekly_llm.py", "weekly_llm_data")
        ]
        
        for script_name, table_name in scripts_to_check:
            result = conn.execute(text("""
                SELECT last_run_date, frequency 
                FROM ingestion_metadata 
                WHERE script_name = :script_name
            """), {"script_name": script_name})
            row = result.fetchone()
            
            if row:
                last_run = row[0]
                frequency = row[1]
                if last_run:
                    print(f"   {script_name}: {last_run} (frequency: {frequency})")
                else:
                    print(f"   {script_name}: Never run (frequency: {frequency})")
            else:
                print(f"   {script_name}: Not found in metadata")
        
        # Summary
        print(f"\n📋 SUMMARY:")
        print(f"   Total tickers: {total_tickers}")
        print(f"   With prices: {tickers_with_prices} ({tickers_with_prices/total_tickers*100:.1f}%)")
        print(f"   With allocations: {tickers_with_allocations} ({tickers_with_allocations/total_tickers*100:.1f}%)")
        print(f"   With profiles: {tickers_with_profiles} ({tickers_with_profiles/total_tickers*100:.1f}%)")
        print(f"   Ready for LLM: {tickers_for_llm} ({tickers_for_llm/total_tickers*100:.1f}%)")
        
        if tickers_for_llm == 0:
            print(f"\n❌ ISSUE: No tickers have all required data (prices + allocations + profiles)")
            print(f"   This is why the LLM script shows 'No tickers found with sufficient data'")
        else:
            print(f"\n✅ SUCCESS: {tickers_for_llm} tickers are ready for LLM processing")

if __name__ == "__main__":
    validate_llm_data()
