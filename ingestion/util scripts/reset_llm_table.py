import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone, date, timedelta

# Load environment variables
load_dotenv(override=True)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

def reset_llm_table():
    """
    Reset the weekly_llm_data table by deleting all records
    and reset the last_run_date for fetch_weekly_llm.py to force it to run again
    """
    session = Session()
    try:
        print("🔄 Resetting weekly_llm_data table...")
        
        # Delete all records from the table
        deleted_count = session.execute(text("DELETE FROM weekly_llm_data"))
        
        print(f"✅ Successfully deleted all records from weekly_llm_data table")
        print(f"   Records deleted: {deleted_count.rowcount}")
        
        # Reset the last_run_date for fetch_weekly_llm.py to more than a week ago
        # This will force the script to run again when run_all.py is executed
        week_ago = date.today() - timedelta(days=8)  # 8 days ago to ensure it runs
        
        reset_result = session.execute(text("""
            UPDATE ingestion_metadata 
            SET last_run_date = :week_ago 
            WHERE script_name = 'fetch_weekly_llm.py'
        """), {"week_ago": week_ago})
        
        session.commit()
        
        print(f"✅ Reset last_run_date for fetch_weekly_llm.py to {week_ago}")
        print(f"   Rows updated: {reset_result.rowcount}")
        
        # Verify the table is empty
        result = session.execute(text("SELECT COUNT(*) FROM weekly_llm_data"))
        count = result.scalar()
        print(f"   Current record count: {count}")
        
        # Verify the last_run_date was updated
        date_result = session.execute(text("""
            SELECT last_run_date FROM ingestion_metadata 
            WHERE script_name = 'fetch_weekly_llm.py'
        """))
        last_run = date_result.scalar()
        print(f"   fetch_weekly_llm.py last_run_date: {last_run}")
        
    except Exception as e:
        print(f"❌ Error resetting table: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    reset_llm_table()
