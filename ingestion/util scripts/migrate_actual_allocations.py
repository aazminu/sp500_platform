import os
import psycopg2
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")

def migrate_existing_allocations():
    """
    Migrate existing allocations to actual_portfolio_allocations table
    This is a one-time script to populate historical data
    """
    
    # First, add a unique constraint if it doesn't exist
    add_constraint_sql = """
    ALTER TABLE actual_portfolio_allocations 
    ADD CONSTRAINT unique_ticker_date UNIQUE (ticker, allocation_date);
    """
    
    # Then migrate the data
    migrate_sql = """
    INSERT INTO actual_portfolio_allocations 
    (ticker, allocation_date, actual_allocation_pct, portfolio_value, position_value)
    SELECT 
        ticker,
        allocation_date,
        allocation_pct,
        100000.00,  -- Assume $100k portfolio for historical data
        allocation_pct * 100000.00
    FROM allocations 
    WHERE allocation_date >= '2024-01-01'  -- Adjust date as needed
    ON CONFLICT (ticker, allocation_date) DO NOTHING;
    """
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            print("Adding unique constraint...")
            try:
                cur.execute(add_constraint_sql)
                print(" Added unique constraint")
            except psycopg2.errors.DuplicateTable:
                print("ℹUnique constraint already exists")
            
            print("Migrating allocation data...")
            cur.execute(migrate_sql)
            conn.commit()
            print(f"Migrated {cur.rowcount} allocation records")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        raise

if __name__ == "__main__":
    migrate_existing_allocations()
