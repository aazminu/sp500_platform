from datetime import date, datetime, timedelta
import requests
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
from dotenv import load_dotenv
import time
import os


"""
What it does: Fetches historical analyst ratings (buy/hold/sell/strong sell) 
for all tickers from the Financial Modeling Prep API, going back 3 years by default.
How it works: Loops through all tickers in the database, makes API calls to FMP with a 0.21-second delay
between requests to respect rate limits, filters for recent data since the specified date, and processes each rating record.
Data storage: Stores records in the grades_historical table with columns 
for symbol, rating date, analyst ratings counts for each category (buy/hold/sell/strong sell), and source (FMP), using upsert logic to avoid duplicates based on symbol and rating date.
"""
#Weekly

# Load environment (override if already set)
load_dotenv(override=True)

# Configuration
# Define a delay to stay within API rate limits
API_REQUEST_DELAY = 0.21  # seconds

DATABASE_URL = os.getenv('DATABASE_URL')
FMP_API_KEY  = os.getenv('FMP_API_KEY')

# SQLAlchemy setup
engine   = create_engine(DATABASE_URL)
Session  = sessionmaker(bind=engine)
metadata = MetaData()
metadata.reflect(bind=engine)

tickers_table           = metadata.tables['tickers']
grades_historical_table = metadata.tables['grades_historical']

def fetch(from_date):
    session = Session()
    if isinstance(from_date, str):
        from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    today = date.today()
    inserted = updated = skipped = 0
    try:
        tickers = [t[0] for t in session.query(tickers_table.c.ticker).all()]
        for ticker in tickers:
            url   = (
                f"https://financialmodelingprep.com/stable/grades-historical"
                f"?symbol={ticker}&apikey={FMP_API_KEY}"
            )
            try:
                resp = requests.get(url)
                print(f"Fetching historical grades for {ticker}...")
                time.sleep(API_REQUEST_DELAY) # Respect API rate limit
                resp.raise_for_status()
                data = resp.json()

                if not data or not isinstance(data, list):
                    skipped += 1
                    print(f"  -> Skipped {ticker}: No data or invalid format from API for historical grades.")
                    continue

                recent = [
                    r for r in data
                    if r.get("date") and datetime.fromisoformat(r.get("date")).date() >= from_date
                ]
                if not recent:
                    skipped += 1
                    print(f"  -> No recent historical grades found for {ticker} since {from_date}.")
                    continue

                for rec in recent:
                    stmt = insert(grades_historical_table).values(
                        symbol                      = rec.get("symbol"),
                        rating_date                 = rec.get("date"),
                        analyst_ratings_buy         = rec.get("analystRatingsBuy"),
                        analyst_ratings_hold        = rec.get("analystRatingsHold"),
                        analyst_ratings_sell        = rec.get("analystRatingsSell"),
                        analyst_ratings_strong_sell = rec.get("analystRatingsStrongSell"),
                        source                      = 'FMP'
                    ).on_conflict_do_update(
                        index_elements=['symbol','rating_date'],
                        set_={
                          'analyst_ratings_buy':         rec.get("analystRatingsBuy"),
                          'analyst_ratings_hold':        rec.get("analystRatingsHold"),
                          'analyst_ratings_sell':        rec.get("analystRatingsSell"),
                          'analyst_ratings_strong_sell': rec.get("analystRatingsStrongSell"),
                          'source':                      'FMP'
                        }
                    )

                    result = session.execute(stmt)
                    if result.rowcount == 1:
                        inserted += 1
                    else:
                        updated += 1
                print(f"  -> Successfully processed {len(recent)} historical grade records for {ticker}.")

            except Exception as e:
                session.rollback()
                print(f"  -> Error processing historical grades for {ticker}: {e}")
                skipped += 1

        session.commit()
        print(f"\u2705 Grades historical: Inserted={inserted}, Updated={updated}, Skipped={skipped}")
    except Exception as e:
        print(f"An error occurred during the grades historical fetching process: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == '__main__':
    try:
        default_from_date = (date.today() - timedelta(days=365*3)).isoformat()
        fetch(default_from_date)
        
        # Log successful execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_historical_analyst.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_historical_analyst.py", False, str(e))
        raise
