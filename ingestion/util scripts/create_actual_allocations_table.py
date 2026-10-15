import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL")

def create_actual_allocations_table():
    """
    Create the actual_portfolio_allocations table in the existing database
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS actual_portfolio_allocations (
        id SERIAL PRIMARY KEY,
        ticker VARCHAR(10) NOT NULL,
        allocation_date DATE NOT NULL,
        actual_allocation_pct DECIMAL(10,6) NOT NULL,
        portfolio_value DECIMAL(15,2) NOT NULL,
        position_value DECIMAL(15,2) NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        FOREIGN KEY (ticker) REFERENCES tickers(ticker) ON DELETE CASCADE
    );
    """
    
    create_indexes_sql = """
    -- Index for performance
    CREATE INDEX IF NOT EXISTS idx_actual_allocations_date ON actual_portfolio_allocations (allocation_date);
    CREATE INDEX IF NOT EXISTS idx_actual_allocations_ticker_date ON actual_portfolio_allocations (ticker, allocation_date);
    """
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            print("Creating actual_portfolio_allocations table...")
            cur.execute(create_table_sql)
            
            print("Creating indexes...")
            cur.execute(create_indexes_sql)
            
            conn.commit()
            print("Successfully created actual_portfolio_allocations table and indexes")
            
            # Verify the table was created
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'actual_portfolio_allocations'
            """)
            if cur.fetchone()[0] > 0:
                print("Table verification successful")
            else:
                print("Table creation failed")
                
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        raise

if __name__ == "__main__":
    create_actual_allocations_table()
