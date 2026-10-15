#!/usr/bin/env python3
import os
import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv

# Export all database tables to CSV files in the updated_csvs folder
# Uses the same DATABASE_URL environment variable as other scripts
load_dotenv(override=True)
# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Handle postgres:// to postgresql:// conversion (for Render compatibility)
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# All tables from your schema.sql
TABLES = [
    "tickers",
    "prices", 
    "analyst_labels",
    "analyst_estimates",
    "grades_historical",
    "stock_news",
    "key_metrics",
    "profiles",
    "allocations",
    "predictions",
    "weekly_llm_data",
    "weekly_stats",
    "ingestion_metadata"
]

def ensure_updated_csvs_folder():
    """Create the updated_csvs folder if it doesn't exist"""
    folder_path = "updated_csvs"
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created folder: {folder_path}")
    return folder_path

def main():
    # Ensure the output folder exists
    output_folder = ensure_updated_csvs_folder()
    
    # Connect to database
    print(f"Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    
    try:
        for table in TABLES:
            filename = os.path.join(output_folder, f"{table}.csv")
            print(f"Exporting {table} → {filename} ...", end="", flush=True)
            
            try:
                with conn.cursor() as cur, open(filename, "w", newline="", encoding='utf-8') as f:
                    cur.copy_expert(f"COPY {table} TO STDOUT WITH CSV HEADER", f)
                print(" done.")
            except psycopg2.Error as e:
                print(f" failed: {e}")
                # Continue with other tables even if one fails
                continue
                
    finally:
        conn.close()
    
    print(f"\nExport completed! CSV files saved in: {output_folder}/")

if __name__ == "__main__":
    main()
