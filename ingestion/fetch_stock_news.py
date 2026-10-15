from datetime import date, datetime, timedelta
import requests
from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
from dotenv import load_dotenv
import time
import os

"""
What it does: Fetches stock news (headlines, summaries, and URLs) for all S&P 500 stocks from the Financial Modeling Prep API, going back 3 years by default.
How it works: Loops through each ticker in the database, makes API calls with a 0.21-second delay to respect rate limits, filters for recent data since the specified date, and processes each news item.
Data storage: Stores records in the stock_news table with columns for url, symbol, published_date, publisher, title, image, site, text, and source='FMP', using upsert logic to avoid duplicates.
"""

#Daily

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

tickers_table   = metadata.tables['tickers']
stock_news_table = metadata.tables['stock_news']

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
                f"https://financialmodelingprep.com/stable/news/stock"
                f"?symbols={ticker}"
                f"&from={from_date.isoformat()}"
                f"&to={today.isoformat()}"
                f"&limit=50"
                f"&apikey={FMP_API_KEY}"
            )
            resp = requests.get(url)
            print(f"Fetching stock news for {ticker}...")
            time.sleep(API_REQUEST_DELAY) # Respect API rate limit
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                skipped += 1
                print(f"  -> No stock news data returned or invalid format for {ticker}.")
                continue

            news_to_process_for_ticker = []
            for rec in data:
                pub_dt = datetime.strptime(rec["publishedDate"], "%Y-%m-%d %H:%M:%S")
                if pub_dt.date() >= from_date:
                    news_to_process_for_ticker.append(rec)
            
            if not news_to_process_for_ticker:
                print(f"  -> No stock news for {ticker} since {from_date} (out of {len(data)} fetched).")
                continue

            print(f"  -> Processing {len(news_to_process_for_ticker)} news items for {ticker} since {from_date}.")
            items_processed_for_ticker = 0
            for rec in news_to_process_for_ticker:
                pub_dt = datetime.strptime(rec["publishedDate"], "%Y-%m-%d %H:%M:%S")
                stmt = insert(stock_news_table).values(
                    url            = rec["url"],
                    symbol         = rec["symbol"],
                    published_date = pub_dt,
                    publisher      = rec.get("publisher"),
                    title          = rec.get("title"),
                    image          = rec.get("image"),
                    site           = rec.get("site"),
                    text           = rec.get("text"),
                    source         = 'FMP'
                ).on_conflict_do_update(
                    index_elements=['url'],
                    set_={
                      'symbol':          rec["symbol"],
                      'published_date':  pub_dt,
                      'publisher':       rec.get("publisher"),
                      'title':           rec.get("title"),
                      'image':           rec.get("image"),
                      'site':            rec.get("site"),
                      'text':            rec.get("text"),
                      'source':          'FMP'
                    }
                )

                res = session.execute(stmt)
                if res.rowcount == 1:
                    inserted += 1
                else:
                    updated += 1
                items_processed_for_ticker +=1
            
            if items_processed_for_ticker > 0:
                print(f"  -> Finished processing {items_processed_for_ticker} news items for {ticker}.")

        session.commit()
        print(f"\u2705 Stock news since {from_date}: Inserted={inserted}, Updated={updated}, Skipped={skipped}")
    except Exception as e:
        print(f"  -> Error during stock news processing for {ticker if 'ticker' in locals() else 'unknown ticker'}: {e}")
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
        log_script_execution("fetch_stock_news.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("fetch_stock_news.py", False, str(e))
        raise
