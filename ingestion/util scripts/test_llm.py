import requests
import json
import os
import time
from datetime import date, timedelta, datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, insert, Column, Integer, String, JSON, DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import re

# Load environment variables
load_dotenv(override=True)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
LLM_KEY = os.getenv("LLM_KEY")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")
if not LLM_KEY:
    raise ValueError("LLM_KEY environment variable is not set")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

# Define the weekly_llm_data table model
class WeeklyLLMData(Base):
    __tablename__ = 'weekly_llm_data'
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), nullable=False)
    week_start_date = Column(DateTime, nullable=False)
    prompt_data = Column(JSON, nullable=False)
    response_data = Column(JSON)
    status = Column(String(20), default='pending')
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc))

# Custom JSON encoder to handle date and decimal objects
class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif hasattr(obj, '__float__'):  # Handle Decimal, Fraction, etc.
            return float(obj)
        return super().default(obj)

def serialize_for_json(data):
    """
    Serialize data for JSON storage, handling dates and other non-serializable objects
    """
    return json.loads(json.dumps(data, cls=DateEncoder))

def get_full_data_for_ticker(conn, ticker):
    """
    Helper to fetch and build the full_data dict for a given ticker, using current date - 7 days for snapshot.
    """
    today = date.today()
    snapshot_date = today - timedelta(days=7)  # Use current date - 7 days for snapshot
    week_ago = today - timedelta(days=7)
    year_ago = today - timedelta(days=365)

    # Get snapshot date (use snapshot_date instead of latest allocation_date)
    snapshot = snapshot_date.isoformat()

    # Previous allocation pct (previous week)
    prev_alloc_row = conn.execute(text("""
        SELECT allocation_pct FROM allocations WHERE ticker = :ticker AND allocation_date < :week_ago ORDER BY allocation_date DESC LIMIT 1
    """), {"ticker": ticker, "week_ago": week_ago}).mappings().fetchone()
    previous_allocation_pct = float(prev_alloc_row["allocation_pct"]) if prev_alloc_row else None

    # Profile summary (from profiles)
    profile_row = conn.execute(text("""
        SELECT profile_data FROM profiles WHERE ticker = :ticker AND date_fetched >= :week_ago ORDER BY date_fetched DESC LIMIT 1
    """), {"ticker": ticker, "week_ago": week_ago}).fetchone()
    profile_summary = profile_row[0] if profile_row else None

    # Weekly: grades_historical, allocations, predictions (last 7 days)
    weekly = {}
    weekly["grades_historical"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM grades_historical WHERE symbol = :ticker AND rating_date >= :week_ago ORDER BY rating_date DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]
    weekly["allocations"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM allocations WHERE ticker = :ticker AND allocation_date >= :week_ago ORDER BY allocation_date DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]
    weekly["predictions"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM weekly_llm_data WHERE ticker = :ticker AND created_at >= :week_ago ORDER BY created_at DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]

    # Daily: prices, analyst_labels, stock_news (last 7 days)
    daily = {}
    daily["prices"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM prices WHERE ticker = :ticker AND price_date >= :week_ago ORDER BY price_date DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]
    daily["analyst_labels"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM analyst_labels WHERE ticker = :ticker AND label_date >= :week_ago ORDER BY label_date DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]
    daily["stock_news"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM stock_news WHERE symbol = :ticker AND published_date >= :week_ago ORDER BY published_date DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]

    # Quarterly: tickers, analyst_estimates (last 4 quarters)
    quarterly = {}
    quarterly["tickers"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM tickers WHERE ticker = :ticker
    """), {"ticker": ticker}).mappings()]
    quarterly["analyst_estimates"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM analyst_estimates WHERE symbol = :ticker AND report_date >= :year_ago ORDER BY report_date DESC
    """), {"ticker": ticker, "year_ago": year_ago}).mappings()]

    # Annual: key_metrics, profiles (last 1 year)
    annual = {}
    annual["key_metrics"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM key_metrics WHERE ticker = :ticker AND date >= :year_ago ORDER BY date DESC
    """), {"ticker": ticker, "year_ago": year_ago}).mappings()]
    annual["profiles"] = [dict(row) for row in conn.execute(text("""
        SELECT * FROM profiles WHERE ticker = :ticker AND date_fetched >= :year_ago ORDER BY date_fetched DESC
    """), {"ticker": ticker, "year_ago": year_ago}).mappings()]

    # Calculate weekly volatility and average volume
    weekly_volatility = 0
    weekly_avg_vol = 0
    if daily["prices"]:
        prices = daily["prices"]
        if len(prices) > 1:
            # Calculate price volatility (standard deviation of returns)
            returns = []
            for i in range(1, len(prices)):
                prev_price = float(prices[i-1].get('close_price', 0))
                curr_price = float(prices[i].get('close_price', 0))
                if prev_price > 0:
                    returns.append((curr_price - prev_price) / prev_price)
            
            if returns:
                import statistics
                weekly_volatility = statistics.stdev(returns) * 100  # Convert to percentage
        
        # Calculate average volume
        volumes = [float(price.get('volume', 0)) for price in prices if price.get('volume')]
        if volumes:
            weekly_avg_vol = sum(volumes) / len(volumes)

    # Calculate quarterly volatility and average volume
    quarterly_volatility = 0
    quarterly_avg_vol = 0
    quarterly_prices = [dict(row) for row in conn.execute(text("""
        SELECT * FROM prices WHERE ticker = :ticker AND price_date >= :year_ago ORDER BY price_date DESC
    """), {"ticker": ticker, "year_ago": year_ago}).mappings()]
    
    if quarterly_prices:
        if len(quarterly_prices) > 1:
            # Calculate quarterly price volatility
            returns = []
            for i in range(1, len(quarterly_prices)):
                prev_price = float(quarterly_prices[i-1].get('close_price', 0))
                curr_price = float(quarterly_prices[i].get('close_price', 0))
                if prev_price > 0:
                    returns.append((curr_price - prev_price) / prev_price)
            
            if returns:
                import statistics
                quarterly_volatility = statistics.stdev(returns) * 100  # Convert to percentage
        
        # Calculate quarterly average volume
        volumes = [float(price.get('volume', 0)) for price in quarterly_prices if price.get('volume')]
        if volumes:
            quarterly_avg_vol = sum(volumes) / len(volumes)

    # Yearly return pct (from prices, 1 year ago vs now)
    price_now_row = conn.execute(text("""
        SELECT close_price FROM prices WHERE ticker = :ticker ORDER BY price_date DESC LIMIT 1
    """), {"ticker": ticker}).mappings().fetchone()
    price_year_ago_row = conn.execute(text("""
        SELECT close_price FROM prices WHERE ticker = :ticker AND price_date <= :year_ago ORDER BY price_date DESC LIMIT 1
    """), {"ticker": ticker, "year_ago": year_ago}).mappings().fetchone()
    yearly_return_pct = None
    if price_now_row and price_year_ago_row and price_year_ago_row["close_price"]:
        yearly_return_pct = 100.0 * (float(price_now_row["close_price"]) - float(price_year_ago_row["close_price"])) / float(price_year_ago_row["close_price"])

    # Latest label
    latest_label = conn.execute(text("""
        SELECT * FROM analyst_labels WHERE ticker = :ticker ORDER BY label_date DESC LIMIT 1
    """), {"ticker": ticker}).mappings().fetchone()

    # Latest estimate
    latest_est = conn.execute(text("""
        SELECT * FROM analyst_estimates WHERE symbol = :ticker ORDER BY report_date DESC LIMIT 1
    """), {"ticker": ticker}).mappings().fetchone()

    # Grades summary (latest grades_historical)
    grades_summary = conn.execute(text("""
        SELECT * FROM grades_historical WHERE symbol = :ticker ORDER BY rating_date DESC LIMIT 1
    """), {"ticker": ticker}).mappings().fetchone()

    # Key metrics (latest)
    key_metrics = conn.execute(text("""
        SELECT * FROM key_metrics WHERE ticker = :ticker ORDER BY date DESC LIMIT 1
    """), {"ticker": ticker}).mappings().fetchone()

    # News: last 7 days
    news = [dict(row) for row in conn.execute(text("""
        SELECT * FROM stock_news WHERE symbol = :ticker AND published_date >= :week_ago ORDER BY published_date DESC
    """), {"ticker": ticker, "week_ago": week_ago}).mappings()]

    return {
        "ticker": ticker,
        "snapshot": snapshot,
        "previous_allocation_pct": previous_allocation_pct,
        "profile_summary": profile_summary,
        "weekly": weekly,
        "daily": daily,
        "quarterly": quarterly,
        "annual": annual,
        "yearly_return_pct": yearly_return_pct,
        "latest_label": dict(latest_label) if latest_label else None,
        "latest_est": dict(latest_est) if latest_est else None,
        "grades_summary": dict(grades_summary) if grades_summary else None,
        "key_metrics": dict(key_metrics) if key_metrics else None,
        "news": news,
        "weekly_volatility": weekly_volatility,
        "weekly_avg_vol": weekly_avg_vol,
        "quarterly_volatility": quarterly_volatility,
        "quarterly_avg_vol": quarterly_avg_vol
    }

def create_prompt_for_ticker(full_data):
    """
    Create a prompt for the LLM based on the ticker data in the required format
    """
    ticker = full_data['ticker']
    snapshot = full_data['snapshot']
    profile = full_data['profile_summary']
    latest_price = full_data['daily']['prices'][0] if full_data['daily']['prices'] else None
    latest_news = full_data['daily']['stock_news'][:2] if full_data['daily']['stock_news'] else []
    latest_estimates = full_data['quarterly']['analyst_estimates'][:1] if full_data['quarterly']['analyst_estimates'] else []
    previous_allocation = full_data['previous_allocation_pct']
    yearly_return = full_data['yearly_return_pct']
    
    # Multiply allocation percentages by 100 for the model (S = 100)
    S = 100
    scaled_previous_allocation = previous_allocation * S if previous_allocation else 0
    
    # Extract news headlines (limit to 2 headlines, max 100 chars each)
    news_headlines = []
    for news in latest_news[:2]:
        title = news.get('title', '')
        if title:
            truncated_title = title[:100] + "..." if len(title) > 100 else title
            news_headlines.append(truncated_title)
    
    # Extract first sentence from profile description
    profile_summary = "No profile data available"
    if profile and isinstance(profile, dict) and 'description' in profile:
        description = profile['description']
        if description:
            # Find the first sentence (ends with . ! or ?)
            first_sentence_end = -1
            for char in ['.', '!', '?']:
                pos = description.find(char)
                if pos != -1 and (first_sentence_end == -1 or pos < first_sentence_end):
                    first_sentence_end = pos
            
            if first_sentence_end != -1:
                profile_summary = description[:first_sentence_end + 1].strip()
            else:
                # If no sentence ending found, take first 150 characters
                profile_summary = description[:150].strip()
    
    # Simplified data object to reduce prompt length
    data_obj = {
        "ticker": ticker,
        "snapshot": snapshot,
        "previous_allocation_pct": scaled_previous_allocation,
        "profile_summary": profile_summary,
        "latest_price": latest_price.get('close_price', 'N/A') if latest_price else 'N/A',
        "yearly_return_pct": yearly_return if yearly_return else 0,
        "weekly_volatility": full_data.get('weekly_volatility', 0),
        "weekly_avg_vol": full_data.get('weekly_avg_vol', 0),
        "recent_news_count": len(latest_news),
        "recent_news_headlines": news_headlines,
        "key_metrics": {
            "pe_ratio": full_data.get('key_metrics', {}).get('metrics', {}).get('peRatio', 'N/A'),
            "market_cap": full_data.get('key_metrics', {}).get('metrics', {}).get('marketCap', 'N/A'),
            "debt_to_equity": full_data.get('key_metrics', {}).get('metrics', {}).get('debtToEquity', 'N/A')
        }
    }
    
    # Convert the data object to JSON string
    data_json = json.dumps(data_obj, cls=DateEncoder)
    
    prompt = f"""<s>[INST] <<SYS>>
You are a portfolio optimization assistant.

For a given stock snapshot, recommend how the allocation should be adjusted.
Your response MUST be valid JSON matching this schema:
{{
  "ticker": "<string>",
  "snapshot": "<YYYY-MM-DD>",
  "verdict": "<Increase|Decrease|Hold|Add|Remove>",
  "new_alloc_pct": <number>,
  "reasoning": "<short explanation>"
}}

IMPORTANT: Allocation percentages are scaled by 100 (S=100). 
- Input previous_allocation_pct is in basis points (1.00 = 100 basis points = 1%)
- Output new_alloc_pct should also be in basis points (e.g., 150 = 1.5%, 250 = 2.5%)
- This scaling helps the model work with more precise decimal values

Do not include any extra keys or commentary. At the end, emit only the JSON.

<</SYS>>

DATA:
{data_json}

Please produce the JSON response.[/INST]"""

    print(f"📊 Prompt statistics:")
    print(f"   Total prompt length: {len(prompt)} characters")
    print(f"   Data JSON length: {len(data_json)} characters")
    
    return prompt

def call_render_endpoint(prompt):
    """
    Call the Render endpoint with the prompt
    """
    url = "https://api.runpod.ai/v2/75lfr05y2bgbmr/run"
    headers = {
        "Authorization": f"Bearer {LLM_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "input": {
            "prompt": prompt
        ,
        "sampling_params": {
            "temperature": 0,
            "top_p": 1.0,
            "max_tokens": 1024,
            "repetition_penalty": 1.0
        }
    }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error calling Render endpoint: {e}")
        return None

def poll_for_result(request_id, max_wait_time=300):
    """
    Poll for the result of an async request
    """
    url = f"https://api.runpod.ai/v2/75lfr05y2bgbmr/status/{request_id}"
    headers = {
        "Authorization": f"Bearer {LLM_KEY}",
        "Content-Type": "application/json"
    }
    
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            status = result.get('status')
            print(f"  Status: {status}")
            
            if status == 'COMPLETED':
                return result
            elif status == 'FAILED':
                print(f"  Request failed: {result}")
                return None
            elif status in ['IN_QUEUE', 'IN_PROGRESS']:
                print(f"  Waiting... ({int(time.time() - start_time)}s elapsed)")
                time.sleep(5)  # Wait 5 seconds before polling again
            else:
                print(f"  Unknown status: {status}")
                time.sleep(5)
                
        except Exception as e:
            print(f"  Error polling for result: {e}")
            time.sleep(5)
    
    print(f"  Timeout after {max_wait_time} seconds")
    return None

def create_default_json_response(ticker, text):
    """
    Create a default JSON response when parsing fails
    """
    try:
        # Try to extract any useful information from the text
        ticker_match = re.search(r'"ticker":\s*"([^"]+)"', text)
        extracted_ticker = ticker_match.group(1) if ticker_match else ticker
        
        snapshot_match = re.search(r'"snapshot":\s*"([^"]+)"', text)
        snapshot = snapshot_match.group(1) if snapshot_match else "2025-08-16"
        
        verdict_match = re.search(r'"verdict":\s*"([^"]+)"', text)
        verdict = verdict_match.group(1) if verdict_match else "Hold"
        
        alloc_match = re.search(r'"new_alloc_pct":\s*([0-9.]+)', text)
        new_alloc_pct = float(alloc_match.group(1)) if alloc_match else 0.0
        
        reasoning_match = re.search(r'"reasoning":\s*"([^"]*)"', text)
        reasoning = reasoning_match.group(1) if reasoning_match else "Unable to parse response"
        
        # Create the proper JSON structure
        default_response = {
            "ticker": extracted_ticker,
            "snapshot": snapshot,
            "verdict": verdict,
            "new_alloc_pct": new_alloc_pct / 100,  # Convert from basis points
            "reasoning": reasoning
        }
        
        print(f"🔧 Created default JSON response: {default_response}")
        return default_response
        
    except Exception as e:
        print(f"❌ Error creating default response: {e}")
        # Ultimate fallback
        return {
            "ticker": ticker,
            "snapshot": "2025-08-16",
            "verdict": "Hold",
            "new_alloc_pct": 0.0,
            "reasoning": "Failed to parse LLM response"
        }

def extract_llm_response(resp):
    """
    Accepts RunPod /status payloads in multiple shapes and returns:
      - parsed JSON (dict) if the model emitted JSON, or
      - raw text (str) as a fallback
    """
    try:
        if not resp:
            return None

        out = resp.get("output")
        if out is None:
            return None

        # 1) Plain string output
        if isinstance(out, str):
            text = out

        # 2) Dict output (OpenAI-style or wrapper)
        elif isinstance(out, dict):
            # common fields seen in workers
            if "text" in out and isinstance(out["text"], str):
                text = out["text"]
            elif "output" in out and isinstance(out["output"], str):
                text = out["output"]
            elif "choices" in out and out["choices"]:
                ch0 = out["choices"][0]
                # OpenAI compat: message.content or just .text
                text = (ch0.get("message", {}).get("content")
                        or ch0.get("text")
                        or "")
            else:
                # last resort: stringify dict
                text = json.dumps(out)

        # 3) List output (streamed chunks or token lists)
        elif isinstance(out, list):
            # Handle tokenized output from RunPod
            text = ""
            for item in out:
                if isinstance(item, str):
                    text += item
                elif isinstance(item, dict):
                    if "output" in item and isinstance(item["output"], str):
                        text += item["output"]
                    elif "text" in item and isinstance(item["text"], str):
                        text += item["text"]
                    elif "choices" in item and item["choices"]:
                        ch0 = item["choices"][0]
                        if "tokens" in ch0 and isinstance(ch0["tokens"], list):
                            # Join tokens and clean up newlines
                            tokens_text = "".join(ch0["tokens"])
                            # Remove extra newlines and spaces
                            tokens_text = tokens_text.replace("\n\n", "").replace("\n", "")
                            text += tokens_text
                        else:
                            text += (ch0.get("text") or ch0.get("message", {}).get("content") or "")
                    elif "tokens" in item:
                        toks = item["tokens"]
                        if isinstance(toks, list):
                            tokens_text = "".join(toks)
                            tokens_text = tokens_text.replace("\n\n", "").replace("\n", "")
                            text += tokens_text
                        else:
                            text += str(toks)

        else:
            # unknown type
            text = str(out)

        if not text:
            return None

        print(f" Raw response text: '{text}'")
        print(f" Response length: {len(text)} characters")

        # Try to extract and fix the JSON
        json_start = text.find('{')
        if json_start != -1:
            json_content = text[json_start:]
            
            # Fix common issues
            fixed_json = json_content.replace("'", '"')
            
            # Remove trailing characters after last }
            last_brace = fixed_json.rfind('}')
            if last_brace != -1:
                fixed_json = fixed_json[:last_brace + 1]
            
            try:
                parsed_json = json.loads(fixed_json)
                print(f"✅ Successfully parsed JSON: {fixed_json}")
                
                # Divide new_alloc_pct by S (100) to convert back to decimal form
                S = 100
                if 'new_alloc_pct' in parsed_json and isinstance(parsed_json['new_alloc_pct'], (int, float)):
                    original_value = parsed_json['new_alloc_pct']
                    parsed_json['new_alloc_pct'] = parsed_json['new_alloc_pct'] / S
                    print(f"✅ Scaled new_alloc_pct from {original_value} to {parsed_json['new_alloc_pct']} (divided by {S})")
                
                return parsed_json
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing failed: {e}")
                print(f"Attempted to parse: {fixed_json}")
                
                # Try to extract ticker from the response for the default function
                ticker_match = re.search(r'"ticker":\s*"([^"]+)"', text)
                ticker = ticker_match.group(1) if ticker_match else "UNKNOWN"
                
                # Create default JSON response
                return create_default_json_response(ticker, text)

        print(f"❌ No JSON found in response: {text}")
        return create_default_json_response("UNKNOWN", text)
        
    except Exception as e:
        print(f"Extractor error: {e}")
        return create_default_json_response("UNKNOWN", "Error in response processing")
    
    
def save_to_database(ticker, response_data=None, status='pending'):
    """
    Save the response to the database (without storing the large prompt)
    First deletes any existing data for this ticker to ensure clean test data
    """
    session = Session()
    try:
        # First, delete any existing data for this ticker
        print(f"🗑️  Clearing existing data for {ticker}...")
        deleted_count = session.query(WeeklyLLMData).filter(
            WeeklyLLMData.ticker == ticker
        ).delete()
        if deleted_count > 0:
            print(f"   Deleted {deleted_count} existing records for {ticker}")
        session.commit()
        
        # Calculate week start date (Monday of current week)
        today = date.today()
        week_start_date = today - timedelta(days=today.weekday())
        
        # Serialize response data for JSON storage (if provided)
        serialized_response_data = serialize_for_json(response_data) if response_data else None
        
        llm_data = WeeklyLLMData(
            ticker=ticker,
            week_start_date=week_start_date,
            prompt_data=None,  # Don't store the large prompt
            response_data=serialized_response_data,
            status=status
        )
        session.add(llm_data)
        session.commit()
        print(f"✅ Saved LLM data for {ticker} to database")
    except Exception as e:
        print(f"❌ Error saving to database: {e}")
        session.rollback()
    finally:
        session.close()

def process_ticker(ticker, conn):
    """
    Process a single ticker: get data, create prompt, call endpoint, save to DB
    Returns True if successful, False if failed
    """
    print(f"\n{'='*60}")
    print(f"Processing ticker: {ticker}")
    print(f"{'='*60}")
    
    # Get full data for ticker
    full_data = get_full_data_for_ticker(conn, ticker)
    
    # Create prompt
    prompt = create_prompt_for_ticker(full_data)
    print(f"\n Created prompt for {ticker}:")
    print(f"Prompt length: {len(prompt)} characters")
    print(f"Full prompt:")
    print(f"{'='*80}")
    print(prompt)
    print(f"{'='*80}")
    
    # Call Render endpoint
    print(f"\n🌐 Calling Render endpoint for {ticker}...")
    response = call_render_endpoint(prompt)
    
    if response:
        print(f"✅ Received initial response for {ticker}:")
        print(f"Request ID: {response.get('id', 'Unknown')}")
        
        # Check if we need to poll for results
        if response.get('status') in ['IN_QUEUE', 'IN_PROGRESS']:
            print(f"⏳ Polling for completion...")
            final_response = poll_for_result(response.get('id'))
        else:
            final_response = response
        
        if final_response:
            print(f"✅ Received final response for {ticker}:")
            print(f"Raw response: {json.dumps(final_response, indent=2)}")
            
            # Extract the actual LLM response
            llm_response = extract_llm_response(final_response)
            
            if llm_response:
                print(f"📋 Extracted LLM response for {ticker}:")
                print(f"LLM Response: {json.dumps(llm_response, indent=2)}")
                
                # Save the extracted LLM response to database
                save_to_database(ticker, llm_response, 'completed')
                return True  # Success
            else:
                print(f"❌ Failed to extract LLM response for {ticker}")
                # Save raw response anyway
                save_to_database(ticker, final_response, 'failed')
                return False  # Failed
        else:
            print(f"❌ No final response received for {ticker}")
            # Save raw response anyway
            save_to_database(ticker, response, 'failed')
            return False  # Failed
    else:
        print(f"❌ No response received for {ticker}")
        save_to_database(ticker, None, 'failed')
        return False  # Failed

def main():
    """
    Main method to process 1 ticker for testing
    """
    start_time = time.time()  # Start timer
    print("🚀 Starting LLM analysis for 1 ticker...")
    
    # Track success/failure counts
    successful_saves = 0
    failed_saves = 0
    
    with engine.connect() as conn:
        # Get 1 ticker that has sufficient data
        result = conn.execute(text("""
            SELECT DISTINCT t.ticker 
            FROM tickers t
            WHERE t.ticker IN (
                SELECT DISTINCT ticker FROM prices 
                WHERE ticker IN (SELECT DISTINCT ticker FROM allocations)
                AND ticker IN (SELECT DISTINCT ticker FROM profiles)
            )
            ORDER BY t.ticker 
            LIMIT 200
        """))
        
        tickers = [row[0] for row in result.fetchall()]
        
        if not tickers:
            print("❌ No tickers found with sufficient data")
            return
        
        print(f" Found {len(tickers)} ticker with sufficient data: {tickers}")
        
        # Process each ticker
        for ticker in tickers:
            success = process_ticker(ticker, conn)
            if success:
                successful_saves += 1
            else:
                failed_saves += 1
    
    # Calculate and display total time and results
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\n🎉 Completed processing {len(tickers)} ticker!")
    print(f"⏱️  Total execution time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"📊 Results Summary:")
    print(f"   ✅ Successfully saved: {successful_saves}")
    print(f"   ❌ Failed to save: {failed_saves}")
    print(f"   📈 Success rate: {(successful_saves/(successful_saves+failed_saves)*100):.1f}%")

if __name__ == "__main__":
    main()
