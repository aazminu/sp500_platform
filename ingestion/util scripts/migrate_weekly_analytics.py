#!/usr/bin/env python3
"""
Migration script for weekly analytics backbone
Adds nav_weekly, benchmark_weekly tables and extends weekly_stats table
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

def run_migration():
    """
    Run the weekly analytics migration
    """
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    if not DATABASE_URL:
        print("❌ ERROR: DATABASE_URL environment variable not found")
        print("Please set your DATABASE_URL in your .env file")
        return False
    
    try:
        # Create database engine
        engine = create_engine(DATABASE_URL)
        
        print("🔄 Starting weekly analytics migration...")
        print(f"📅 Migration started at: {datetime.now().isoformat()}")
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                print("\n📊 Creating nav_weekly table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS nav_weekly (
                      week_start_date DATE PRIMARY KEY,             -- Monday of the week (ET)
                      as_of_ts       TIMESTAMP NOT NULL DEFAULT NOW(),
                      equity         NUMERIC(18,4) NOT NULL,        -- cash + positions
                      cash           NUMERIC(18,4) NOT NULL,        -- cash balance at snapshot
                      note           TEXT
                    );
                """))
                print("✅ nav_weekly table created successfully")
                
                print("\n📈 Creating benchmark_weekly table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS benchmark_weekly (
                      symbol         VARCHAR(10) NOT NULL DEFAULT 'SPY',
                      week_start_date DATE      NOT NULL,
                      px_date        DATE       NOT NULL,           -- actual trading date of this price
                      adj_close      NUMERIC(12,4) NOT NULL,       -- adjusted close (dividends/splits)
                      PRIMARY KEY (symbol, week_start_date)
                    );
                """))
                print("✅ benchmark_weekly table created successfully")
                
                print("\n🔍 Creating index for benchmark_weekly...")
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_bench_wk_symbol_date
                      ON benchmark_weekly(symbol, week_start_date);
                """))
                print("✅ Index created successfully")
                
                print("\n📋 Extending weekly_stats table...")
                conn.execute(text("""
                    ALTER TABLE weekly_stats
                      ADD COLUMN IF NOT EXISTS benchmark_return_pct DECIMAL(8,4),
                      ADD COLUMN IF NOT EXISTS excess_return_pct    DECIMAL(8,4);
                """))
                print("✅ weekly_stats table extended successfully")
                
                # Commit transaction
                trans.commit()
                print("\n🎉 Migration completed successfully!")
                print("📊 New tables created:")
                print("   - nav_weekly (portfolio NAV snapshots)")
                print("   - benchmark_weekly (benchmark price data)")
                print("📈 weekly_stats table extended with:")
                print("   - benchmark_return_pct")
                print("   - excess_return_pct")
                
                return True
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                print(f"\n❌ Migration failed: {str(e)}")
                print("🔄 Transaction rolled back")
                return False
                
    except Exception as e:
        print(f"❌ Database connection error: {str(e)}")
        return False

def check_migration_status():
    """
    Check if migration has already been applied
    """
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    if not DATABASE_URL:
        print("❌ ERROR: DATABASE_URL environment variable not found")
        return False
    
    try:
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as conn:
            # Check if nav_weekly table exists
            nav_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'nav_weekly'
                );
            """)).fetchone()[0]
            
            # Check if benchmark_weekly table exists
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
            
            print("🔍 Migration Status Check:")
            print(f"   nav_weekly table: {'✅ EXISTS' if nav_exists else '❌ MISSING'}")
            print(f"   benchmark_weekly table: {'✅ EXISTS' if bench_exists else '❌ MISSING'}")
            print(f"   weekly_stats new columns: {'✅ EXISTS' if columns_exist else '❌ MISSING'}")
            
            if nav_exists and bench_exists and columns_exist:
                print("\n✅ Migration appears to be already applied!")
                return True
            else:
                print("\n⚠️  Migration not fully applied")
                return False
                
    except Exception as e:
        print(f"❌ Error checking migration status: {str(e)}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Weekly Analytics Migration Script")
    print("=" * 60)
    
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        # Just check status
        check_migration_status()
    else:
        # Run migration
        print("⚠️  This will modify your database schema!")
        print("📋 Changes to be made:")
        print("   - Create nav_weekly table")
        print("   - Create benchmark_weekly table") 
        print("   - Add benchmark_return_pct and excess_return_pct to weekly_stats")
        print()
        
        response = input("🤔 Do you want to proceed? (y/N): ").strip().lower()
        
        if response in ['y', 'yes']:
            success = run_migration()
            if success:
                print("\n🎉 Migration completed successfully!")
                print("💡 You can now start using the new tables and columns")
            else:
                print("\n❌ Migration failed - please check the errors above")
                sys.exit(1)
        else:
            print("❌ Migration cancelled by user")
            sys.exit(0)
