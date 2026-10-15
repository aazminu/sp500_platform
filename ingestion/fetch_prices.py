import os
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Date, Numeric, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker
import time
import requests

"""
What it does: Fetches daily stock price data (open, high, low, close, volume) for all S&P 500 stocks from the Financial Modeling Prep API, going back 3 years by default.
How it works: Loops through each ticker in the database, makes API calls with a 0.21-second delay to respect rate limits, and processes each price record.
Data storage: Stores records in the prices table with columns for symbol, date, and price data (open, high, low, close, volume), using upsert logic to avoid duplicates.
"""

#Daily

# Load environment variables
load_dotenv(override=True)
FMP_API_KEY  = os.getenv('FMP_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')

if not FMP_API_KEY or not DATABASE_URL:
    raise ValueError("FMP_API_KEY and DATABASE_URL must be set in .env file")

# Define a delay to stay within API rate limits (e.g., FMP allows 300 req/min -> 5 req/sec -> 0.2s/req)
API_REQUEST_DELAY = 0.21  # seconds (for ~285 requests per minute)

# SQLAlchemy setup
Base = declarative_base()
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# ORM model for prices table
class Price(Base):
    __tablename__ = 'prices'
    ticker      = Column(String(10), primary_key=True)
    price_date  = Column(Date,      primary_key=True)
    open_price  = Column(Numeric(12,4))
    high_price  = Column(Numeric(12,4))
    low_price   = Column(Numeric(12,4))
    close_price = Column(Numeric(12,4))
    volume      = Column(BigInteger)

# ORM model for tickers table (to fetch tickers)
class Ticker(Base):
    __tablename__ = 'tickers'
    ticker = Column(String(10), primary_key=True)

def fetch(from_date):
    session = Session()
    try:
        today = date.today()
        if isinstance(from_date, str):
            from_date = datetime.strptime(from_date, "%Y-%m-%d").date()

        tickers = [t[0] for t in session.query(Ticker.ticker).all()]
        total_upserts = 0
        print(f"Found {len(tickers)} tickers to process for price data.")

        for symbol in tickers:
            from_date_str = from_date.isoformat()
            to_date_str = today.isoformat()
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?from={from_date_str}&to={to_date_str}&apikey={FMP_API_KEY}"

            print(f"\nFetching prices for {symbol} (from {from_date_str} to {to_date_str})...")
            response = requests.get(url)
            time.sleep(API_REQUEST_DELAY) # Respect API rate limit
            response.raise_for_status()

            print(f"  Parsing JSON response for {symbol}...")
            data_response = response.json()
            print(f"  Finished parsing JSON for {symbol}.")

            if isinstance(data_response, dict) and 'historical' in data_response:
                historical_data = data_response['historical']
            elif isinstance(data_response, list):
                historical_data = data_response
            else:
                print(f"  Unexpected JSON structure for {symbol}: {type(data_response)}. Skipping.")
                continue

            if not historical_data:
                print(f"  No historical price data returned for {symbol} in the date range.")
                continue

            print(f"  Processing {len(historical_data)} price records for {symbol}...")
            upserts = 0
            for record_idx, record in enumerate(historical_data):
                record_date_str = record.get('date')
                if not record_date_str:
                    print(f"    Skipping record for {symbol} (index {record_idx}) due to missing date: {record}")
                    continue
                try:
                    record_date = datetime.strptime(record_date_str, '%Y-%m-%d').date()
                    price = Price(
                        ticker      = symbol,
                        price_date  = record_date,
                        open_price  = record.get('open'),
                        high_price  = record.get('high'),
                        low_price   = record.get('low'),
                        close_price = record.get('close'),
                        volume      = record.get('volume')
                    )
                    session.merge(price)
                    upserts += 1
                except Exception as e:
                    print(f"    Error processing record for {symbol} on {record_date_str} (index {record_idx}): {e}")

            session.commit() # Commit after processing all records for the current ticker
            print(f"  {symbol}: Upserted and committed {upserts} price records.")
            total_upserts += upserts

        print(f"\n Finished processing all tickers. Total price records upserted: {total_upserts}")
    except Exception as e:
        print(f"Error: {e}")
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
        log_script_execution("fetch_prices.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_prices.py", False, str(e))
        raise
