import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import subprocess
import psycopg2
import time
from sqlalchemy.exc import OperationalError

def wait_for_postgres(database_url, retries=10, delay=3):
    for attempt in range(retries):
        try:
            engine = create_engine(database_url)
            with engine.connect() as conn:
                print("Connected to Postgres!")
                return engine
        except OperationalError as e:
            print(f"Postgres not ready (attempt {attempt+1}/{retries}): {e}")
            time.sleep(delay)
    raise Exception("Could not connect to Postgres after several attempts.")

def init_database():
    try:
        # Load environment variables from .env file
        load_dotenv(override=True)
        
        # Get database URL from environment variable
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            # Construct DATABASE_URL from individual components
            db_host = os.getenv("DB_HOST", "localhost")
            db_port = os.getenv("DB_PORT", "5432")
            db_user = os.getenv("DB_USER", "postgres")
            db_password = os.getenv("DB_PASSWORD", "password")
            db_name = os.getenv("DB_NAME", "sp500_db")
            database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        
        print("Using DATABASE_URL =", database_url)
        
        # Create SQLAlchemy engine
        engine = wait_for_postgres(database_url)
        
        # Read schema.sql file
        schema_path = Path(__file__).parent / 'ingestion' / 'schema.sql'
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        # Execute schema.sql
        with engine.connect() as connection:
            try:
                connection.execute(text(schema_sql))
                connection.commit()
            except Exception as e:
                # If tables already exist, that's fine - just log it
                if "already exists" in str(e):
                    print(" Database schema already exists, skipping creation")
                else:
                    raise e
        
        print("Database schema created successfully")
        #UPDATE WHATS BELOW TO BE MORE ACCURATE
        seed_sql = """
INSERT INTO ingestion_metadata (table_name, frequency, script_name)
VALUES
  ('tickers',           'quarterly', 'fetch_tickers.py'),
  ('prices',            'daily',     'fetch_prices.py'),
  ('analyst_labels',    'daily',     'fetch_analyst_labels.py'),
  ('analyst_estimates', 'quarterly', 'fetch_analyst_estimates.py'),
  ('grades_historical', 'weekly',    'fetch_historical_analyst.py'),
  ('stock_news',        'daily',     'fetch_stock_news.py'),
  ('key_metrics',       'annual',    'fetch_metrics.py'),
  ('profiles',          'annual',    'fetch_profile.py'),
  ('allocations',       'weekly',    'fetch_historical_market_cap.py'),
  ('predictions',       'weekly',    NULL)
ON CONFLICT (table_name) DO UPDATE
  SET frequency = EXCLUDED.frequency,
      script_name = EXCLUDED.script_name;
"""
        with engine.connect() as conn:
            try:
                conn.execute(text(seed_sql))
                conn.commit()
                print(" ingestion_metadata seeded successfully")
            except Exception as e:
                # If data already exists, that's fine - just log it
                if "already exists" in str(e) or "duplicate key" in str(e):
                    print(" ingestion_metadata already exists, skipping seeding")
                else:
                    raise e
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        raise

if __name__ == "__main__":
    init_database()
