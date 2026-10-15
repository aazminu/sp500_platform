import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from pathlib import Path

def drop_all_tables():
    """Drop all tables to start fresh"""
    load_dotenv(override=True)
    database_url = os.getenv('DATABASE_URL')
    engine = create_engine(database_url)
    
    print(" Dropping all existing tables...")
    with engine.connect() as connection:
        # Drop all tables in the correct order (respecting foreign keys)
        drop_sql = """
        DROP TABLE IF EXISTS 
            weekly_llm_data,
            predictions,
            stock_news,
            profiles,
            prices,
            key_metrics,
            grades_historical,
            analyst_labels,
            analyst_estimates,
            allocations,
            tickers,
            ingestion_metadata
        CASCADE;
        """
        connection.execute(text(drop_sql))
        connection.commit()
    print("All tables dropped successfully")

def init_database():
    """Initialize fresh database with schema and metadata"""
    load_dotenv(override=True)
    database_url = os.getenv('DATABASE_URL')
    print("Using DATABASE_URL =", database_url)
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    engine = create_engine(database_url)
    
    # Read and execute schema.sql
    schema_path = Path(__file__).parent.parent / 'schema.sql'
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    
    with engine.connect() as connection:
        connection.execute(text(schema_sql))
        connection.commit()
    print(" Database schema created successfully")
    
    # Seed ingestion_metadata with the actual last run dates you provided
    seed_sql = """
    INSERT INTO ingestion_metadata (table_name, frequency, script_name, last_run_date)
    VALUES
      ('tickers',           'quarterly', 'fetch_tickers.py', '2025-08-25'),
      ('prices',            'daily',     'fetch_prices.py', '2025-08-25'),
      ('analyst_labels',    'daily',     'fetch_analyst_labels.py', '2025-08-25'),
      ('analyst_estimates', 'quarterly', 'fetch_analyst_estimates.py', '2025-08-25'),
      ('grades_historical', 'weekly',    'fetch_historical_analyst.py', '2025-08-25'),
      ('stock_news',        'daily',     'fetch_stock_news.py', '2025-08-25'),
      ('key_metrics',       'annual',    'fetch_metrics.py', '2025-08-25'),
      ('profiles',          'annual',    'fetch_profile.py', '2025-08-25'),
      ('allocations',       'weekly',    'fetch_historical_market_cap.py', '2025-08-25'),
      ('predictions',       'weekly',    NULL, NULL),
      ('weekly_llm_data',   'weekly',    'fetch_weekly_llm.py', NULL),
      ('daily_snapshots',   'daily',     'fetch_daily_snapshots.py', NULL),
      ('nav_weekly',        'daily',     'fetch_daily_snapshots.py', NULL),
      ('benchmark_weekly',  'daily',     'fetch_daily_snapshots.py', NULL)
    ON CONFLICT (table_name) DO UPDATE
      SET frequency = EXCLUDED.frequency,
          script_name = EXCLUDED.script_name,
          last_run_date = EXCLUDED.last_run_date;
    """
    with engine.connect() as conn:
        conn.execute(text(seed_sql))
        conn.commit()
    print("ingestion_metadata seeded with actual last run dates")

def upload_csv_to_table(csv_path, table_name, conn):
    """Upload CSV data to table"""
    with conn.cursor() as cur:
        with open(csv_path, 'r', encoding='utf-8') as f:
            cur.copy_expert(f"COPY {table_name} FROM STDIN WITH CSV HEADER", f)
    conn.commit()
    print(f" Uploaded {csv_path} to {table_name}")

def upload_current_data():
    """Upload all current CSV data"""
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(DATABASE_URL)
    
    csv_table_map = {
        "tickers.csv": "tickers",  # Must be first!
        "allocations.csv": "allocations",
        "analyst_estimates.csv": "analyst_estimates",
        "analyst_labels.csv": "analyst_labels",
        "grades_historical.csv": "grades_historical",
        "key_metrics.csv": "key_metrics",
        "prices.csv": "prices",
        "profiles.csv": "profiles",
        "stock_news.csv": "stock_news",
    }
    
    print(" Uploading current CSV data...")
    for csv, table in csv_table_map.items():
        csv_path = f"../../csvs/{csv}"
        if os.path.exists(csv_path):
            print(f"  Uploading {csv} to {table}...")
            upload_csv_to_table(csv_path, table, conn)
        else:
            print(f"{csv} not found, skipping...")
    
    conn.close()
    print("Current data upload complete")



def main():
    """Main function: Delete DB and upload current data"""
    print(" Starting complete database refresh process...")
    
    # Step A: Delete current database
    drop_all_tables()
    
    # Step B: Upload current data
    init_database()
    upload_current_data()
    
    print(" Complete database refresh process finished!")

if __name__ == "__main__":
    main()
