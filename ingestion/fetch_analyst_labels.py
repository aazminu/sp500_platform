from datetime import date, datetime, timedelta
import requests
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
from dotenv import load_dotenv
import time
import os

"""
What it does: Fetches analyst rating data for all tickers from Financial Modeling Prep API, including overall scores, 
individual metric scores (DCF, ROE, ROA, debt-to-equity, P/E, P/B ratios), and analyst ratings.

How it works: Loops through all tickers in the database, makes API calls to FMP's ratings-snapshot endpoint with a 0.21-second delay between requests to respect rate limits,
and processes the JSON response to extract scoring data.

How data is stored: Uses PostgreSQL upsert logic (INSERT ... ON CONFLICT DO UPDATE) 
to store daily records in the analyst_labels table with columns for ticker, date, rating, overall_score, and individual metric scores, updating existing records for the same ticker/date combination.
"""
#Daily

# Load environment with override
load_dotenv(override=True)

# Configuration
# Define a delay to stay within API rate limits
API_REQUEST_DELAY = 0.21  # seconds

DATABASE_URL = os.getenv('DATABASE_URL')
FMP_API_KEY = os.getenv('FMP_API_KEY')

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
metadata = MetaData()
metadata.reflect(bind=engine)

tickers_table = metadata.tables['tickers']
analyst_labels_table = metadata.tables['analyst_labels']

def fetch(from_date):
    session = Session()
    if isinstance(from_date, str):
        from_date = datetime.strptime(from_date, "%Y-%m-%d").date()
    today = date.today()
    inserted = updated = skipped = 0
    try:
        tickers = [t[0] for t in session.query(tickers_table.c.ticker).all()]
        for ticker in tickers:
            url = (
                f"https://financialmodelingprep.com/stable/ratings-snapshot"
                f"?symbol={ticker}&apikey={FMP_API_KEY}"
            )
            try:
                response = requests.get(url)
                print(f"Fetching analyst labels for {ticker}...")
                time.sleep(API_REQUEST_DELAY) # Respect API rate limit
                response.raise_for_status()
                data = response.json()

                if not data or not isinstance(data, list):
                    skipped += 1
                    print(f"  -> Skipped {ticker}: No data or invalid format from API.")
                    continue

                snapshot = data[0]
                rating                     = snapshot.get('rating')
                overall_score              = snapshot.get('overallScore')
                discounted_cash_flow_score = snapshot.get('discountedCashFlowScore')
                return_on_equity_score     = snapshot.get('returnOnEquityScore')
                return_on_assets_score     = snapshot.get('returnOnAssetsScore')
                debt_to_equity_score       = snapshot.get('debtToEquityScore')
                price_to_earnings_score    = snapshot.get('priceToEarningsScore')
                price_to_book_score        = snapshot.get('priceToBookScore')

                if overall_score is None:
                    skipped += 1
                    print(f"  -> Skipped {ticker}: No overall score available.")
                    continue

                stmt = insert(analyst_labels_table).values(
                    ticker=ticker,
                    label_date=today,
                    rating=rating,
                    overall_score=overall_score,
                    discounted_cash_flow_score=discounted_cash_flow_score,
                    return_on_equity_score=return_on_equity_score,
                    return_on_assets_score=return_on_assets_score,
                    debt_to_equity_score=debt_to_equity_score,
                    price_to_earnings_score=price_to_earnings_score,
                    price_to_book_score=price_to_book_score,
                    source='FMP'
                ).on_conflict_do_update(
                    index_elements=['ticker', 'label_date'],
                    set_={
                        'rating': rating,
                        'overall_score': overall_score,
                        'discounted_cash_flow_score': discounted_cash_flow_score,
                        'return_on_equity_score': return_on_equity_score,
                        'return_on_assets_score': return_on_assets_score,
                        'debt_to_equity_score': debt_to_equity_score,
                        'price_to_earnings_score': price_to_earnings_score,
                        'price_to_book_score': price_to_book_score,
                        'source': 'FMP'
                    }
                )

                result = session.execute(stmt)
                if result.rowcount == 1:
                    inserted += 1
                else:
                    updated += 1
                print(f"  -> Successfully processed analyst labels for {ticker}.")

            except Exception as e:
                session.rollback()
                print(f"  -> Error processing analyst labels for {ticker}: {e}")
                skipped += 1

        session.commit()
        print(f"\u2705 Analyst labels: Inserted={inserted}, Updated={updated}, Skipped={skipped}")
    except Exception as e:
        print(f"An error occurred during the analyst labels fetching process: {str(e)}")
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
        log_script_execution("fetch_analyst_labels.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_analyst_labels.py", False, str(e))
        raise
