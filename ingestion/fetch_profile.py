import os
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
import requests
import time

"""
What it does: Fetches company profile data (name, description, industry, sector, etc.) for all S&P 500 stocks from the Financial Modeling Prep API, going back 3 years by default.
How it works: Loops through each ticker in the database, makes API calls with a 0.21-second delay to respect rate limits, and processes each profile record.
Data storage: Stores records in the profiles table with columns for symbol, date, and the full profile data, using upsert logic to avoid duplicates.
"""

#Annual

# Load environment variables
load_dotenv(override=True)
FMP_API_KEY = os.getenv('FMP_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

if not FMP_API_KEY or not DATABASE_URL:
    raise ValueError("FMP_API_KEY and DATABASE_URL must be set in .env file")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
metadata = MetaData()
metadata.reflect(bind=engine)

tickers_table = metadata.tables['tickers']
profiles_table = metadata.tables['profiles']

API_REQUEST_DELAY = 0.21  # seconds (for ~285 requests per minute)

def fetch(from_date):
    session = Session()
    if isinstance(from_date, str):
        from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    today = date.today()
    inserted = updated = skipped = 0
    try:
        # Get all tickers from the tickers table (limit to 5 for testing)
        ticker_symbols = [t[0] for t in session.query(tickers_table.c.ticker).all()]
        total_tickers = len(ticker_symbols)
        print(f"Found {total_tickers} tickers in DB to process for profiles.")

        for idx, ticker in enumerate(ticker_symbols):
            print(f"\nProcessing Ticker {idx + 1}/{total_tickers}: {ticker}")
            try:
                url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={FMP_API_KEY}"
                print(f"  Fetching profile for {ticker}...")
                response = requests.get(url)
                time.sleep(API_REQUEST_DELAY)  # Respect API rate limit
                response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)

                profile_data_list = response.json()

                if not isinstance(profile_data_list, list) or not profile_data_list:
                    print(f"  -> No profile data returned or invalid format for {ticker}.")
                    skipped += 1
                    continue
                
                # The API returns a list with a single profile object
                profile_json = profile_data_list[0]

                stmt = insert(profiles_table).values(
                    ticker=ticker,
                    profile_data=profile_json,
                    date_fetched=today
                ).on_conflict_do_update(
                    index_elements=['ticker'], # Primary key column
                    set_={
                        'profile_data': profile_json,
                        'date_fetched': today
                    }
                )
                res = session.execute(stmt)

                if res.rowcount == 1: # Row was affected (inserted or updated)
                    inserted += 1
                else: # rowcount == 0 (e.g. conflict, but DO UPDATE conditions not met or DO NOTHING)
                    updated += 1
                print(f"  -> Successfully processed profile for {ticker}.")

            except requests.exceptions.HTTPError as http_err:
                print(f"  -> HTTP error fetching profile for {ticker}: {http_err}")
                skipped += 1
            except requests.exceptions.RequestException as req_err:
                print(f"  -> Request error fetching profile for {ticker}: {req_err}")
                skipped += 1
            except Exception as e:
                print(f"  -> Error processing profile for {ticker}: {e}")
                skipped += 1
                continue

        session.commit()
        print(f"\n✅ Profile processing complete: Inserted/Updated={inserted}, Potentially Re-updated={updated}, Skipped Tickers={skipped}")

    except Exception as e:
        print(f"❌ An error occurred during the profile fetching process: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    try:
        default_from_date = (date.today() - timedelta(days=365*3)).isoformat()
        fetch(default_from_date)
        
        # Log successful execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_profile.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_profile.py", False, str(e))
        raise
