import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import json
from datetime import date, timedelta, datetime
import requests
import re
import statistics
import psycopg2

# Alpaca imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

# Load environment variables before anything else
load_dotenv(override=True)

# Initialize Alpaca client
ALPACA_API_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET")

#Sanity Check for Alpaca Clie, KEYS
if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    print("WARNING: ALPACA_KEY or ALPACA_SECRET not initalized in environment variables")
    trading_client = None
else:
    try:
        trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        print("Alpaca client initialized successfully")
    except Exception as e:
        print(f"Error initializing Alpaca client: {e}")
        trading_client = None

#Flask Setup 
app = Flask(__name__)
CORS(app, origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")])

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL is not found in environment variables")
    engine = None
else:
    engine = create_engine(DATABASE_URL)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def check_database_configured():
    """Check if database is configured and return error response if not"""
    if not engine:
        return jsonify({
            "status": "error", 
            "error": "Database not configured. Set DATABASE_URL environment variable."
        }), 500
    return None

def check_alpaca_configured():
    """Check if Alpaca is configured and return error response if not"""
    if trading_client is None:
        return jsonify({
            "status": "error", 
            "error": "Alpaca not configured. Set ALPACA_KEY and ALPACA_SECRET environment variables."
        }), 500
    return None

def _safe_float(value, default=0.0):
    """
    Alpaca fields occasionally come back as None (or as strings).
    This keeps portfolio endpoints from 500'ing on float(None).
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _safe_int_from_float(value, default=0):
    f = _safe_float(value, default=None)
    if f is None:
        return default
    try:
        return int(f)
    except (TypeError, ValueError):
        return default

def get_full_data_for_ticker_llm(conn, ticker):
    """
    Helper to fetch and build the full_data dict for a given ticker, using current date - 7 days for snapshot.
    This function matches the structure from fetch_weekly_llm.py
    """
    today = date.today()
    snapshot_date = today - timedelta(days=7)  # Use current date - 7 days for snapshot
    week_ago = today - timedelta(days=7)
    year_ago = today - timedelta(days=365)

    # Get snapshot date (use snapshot_date instead of latest allocation_date)
    snapshot = snapshot_date.isoformat()

    # Previous ACTUAL allocation pct (from actual_portfolio_allocations table)
    prev_actual_row = conn.execute(text("""
        SELECT actual_allocation_pct FROM actual_portfolio_allocations 
        WHERE ticker = :ticker AND allocation_date < :week_ago 
        ORDER BY allocation_date DESC LIMIT 1
    """), {"ticker": ticker, "week_ago": week_ago}).mappings().fetchone()
    
    # Fallback to FMP allocations if no actual data exists
    if not prev_actual_row:
        prev_alloc_row = conn.execute(text("""
            SELECT allocation_pct FROM allocations WHERE ticker = :ticker AND allocation_date < :week_ago ORDER BY allocation_date DESC LIMIT 1
        """), {"ticker": ticker, "week_ago": week_ago}).mappings().fetchone()
        previous_allocation_pct = float(prev_alloc_row["allocation_pct"]) if prev_alloc_row else None
    else:
        previous_allocation_pct = float(prev_actual_row["actual_allocation_pct"])

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
    if daily["prices"] and len(daily["prices"]) > 1:
        prices = daily["prices"]
        # Calculate price volatility (standard deviation of returns)
        returns = []
        for i in range(1, len(prices)):
            prev_price = float(prices[i-1].get('close_price', 0))
            curr_price = float(prices[i].get('close_price', 0))
            if prev_price > 0:
                returns.append((curr_price - prev_price) / prev_price)
        
        # Only calculate volatility if we have at least 2 returns
        if len(returns) >= 2:
            try:
                weekly_volatility = statistics.stdev(returns) * 100  # Convert to percentage
            except Exception as e:
                print(f"Warning: Could not calculate weekly volatility for {ticker}: {e}")
                weekly_volatility = 0
        
        # Calculate average volume
        volumes = [float(price.get('volume', 0)) for price in prices if price.get('volume')]
        if volumes:
            weekly_avg_vol = sum(volumes) / len(volumes)

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

    # Key metrics (latest)
    key_metrics = conn.execute(text("""
        SELECT * FROM key_metrics WHERE ticker = :ticker ORDER BY date DESC LIMIT 1
    """), {"ticker": ticker}).mappings().fetchone()

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
        "key_metrics": dict(key_metrics) if key_metrics else {},
        "weekly_volatility": weekly_volatility,
        "weekly_avg_vol": weekly_avg_vol
    }

def calculate_volatility_and_volume(prices, ticker, period_name): 
    """Calculate volatility and average volume for a given price dataset.
    Takes in a list of prices, ticker symbol and period name"""
    volatility = 0
    avg_vol = 0
    
    if prices and len(prices) > 1:
        # Calculate price volatility (standard deviation of returns)
        returns = []
        for i in range(1, len(prices)):
            prev_price = float(prices[i-1].get('close_price', 0)) #i-1 gives access to prev price 
            curr_price = float(prices[i].get('close_price', 0)) # current price
            if prev_price > 0: #prev price cant be 0 
                returns.append((curr_price - prev_price) / prev_price) # Difference in pct between prev and curr 
        
        # Only calculate volatility if we have at least 2 returns
        if len(returns) >= 2:
            try:
                volatility = statistics.stdev(returns) * 100  # Convert to percentage
            except Exception as e:
                print(f"Warning: Could not calculate {period_name} volatility for {ticker}: {e}")
                volatility = 0
        
        # Calculate average volume by grabing volumes array for every price and averaging
        
        volumes = [float(price.get('volume', 0)) for price in prices if price.get('volume')]
        
        if volumes:
            avg_vol = sum(volumes) / len(volumes)
    
    return volatility, avg_vol

#Classic prompt creation
def create_prompt_for_ticker(full_data):
    """
    Create a prompt for the LLM based on the ticker data in the required format
    (Same as fetch_weekly_llm.py)
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
    data_json = json.dumps(data_obj)
    
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
    
    return prompt

# ============================================================================
# STOCK ANALYSIS ENDPOINTS (Used by Stepper components)
# ============================================================================

@app.route("/api/stocks", methods=["GET"])
def api_stocks():
    """List all tickers with company name and sector"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, company_name, sector FROM tickers ORDER BY ticker
        """))
        #Creates a dict of all tickers, company names, and sectors 
        stocks = [dict(row) for row in result.mappings()] 
        return jsonify({"status": "ok", "stocks": stocks})

@app.route("/api/stocks/<ticker>/info", methods=["GET"])
def api_stock_info(ticker):
    """Basic info for a ticker: name, sector, profile"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    with engine.connect() as conn:
        ticker_row = conn.execute(text("""
            SELECT ticker, company_name, sector FROM tickers WHERE ticker = :ticker
        """), {"ticker": ticker}).mappings().fetchone()
        profile_row = conn.execute(text("""
            SELECT profile_data FROM profiles WHERE ticker = :ticker
        """), {"ticker": ticker}).fetchone()
        info = dict(ticker_row) if ticker_row else {}
        if profile_row:
            info["profile"] = profile_row[0] # only one profile entry 
        return jsonify({"status": "ok", "info": info})

#Builds prompt 
@app.route("/api/stocks/<ticker>/prompt", methods=["GET"])
def api_stock_prompt(ticker):
    """Return the LLM prompt for a ticker (used by Step3_PromptReview)"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    with engine.connect() as conn:
        # Get basic ticker info
        ticker_row = conn.execute(text("""
            SELECT ticker, company_name, sector FROM tickers WHERE ticker = :ticker
        """), {"ticker": ticker}).mappings().fetchone()
        
        if not ticker_row:
            return jsonify({"status": "error", "error": "Ticker not found"}), 404
        
        # Use the helper function to get full data (same as fetch_weekly_llm.py)
        full_data = get_full_data_for_ticker_llm(conn, ticker)
        
        # Create the prompt using the same function as fetch_weekly_llm.py
        prompt = create_prompt_for_ticker(full_data)
        
        return jsonify({
            "status": "ok", 
            "data": {
                "ticker": ticker,
                "prompt": prompt,
                "full_data": full_data
            }
        })

# ============================================================================
# PORTFOLIO MANAGEMENT ENDPOINTS (Used by Portfolio components)
# ============================================================================

@app.route("/api/account", methods=["GET"])
def api_account():
    """Get account summary information"""
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Get real account data from Alpaca
        account = trading_client.get_account()
        
        account_data = {
            "equity": _safe_float(getattr(account, "equity", None), default=0.0),
            "cash": _safe_float(getattr(account, "cash", None), default=0.0),
            "buying_power": _safe_float(getattr(account, "buying_power", None), default=0.0),
            "portfolio_value": _safe_float(getattr(account, "portfolio_value", None), default=0.0),
            "market_open": account.status == "ACTIVE",
            "last_updated": account.created_at.isoformat() + "Z"
        }
        return jsonify({"status": "ok", "account": account_data})
    except Exception as e:
        print(f"Error fetching account data: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/positions", methods=["GET"])
def api_positions():
    """Get current positions"""
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Get real positions from Alpaca
        positions = trading_client.get_all_positions()
        
        positions_data = []
        for position in positions:
            qty_f = _safe_float(getattr(position, "qty", None), default=0.0)
            if qty_f != 0:  # Only include non-zero positions
                positions_data.append({
                    "symbol": getattr(position, "symbol", None),
                    "qty": _safe_int_from_float(getattr(position, "qty", None), default=0),
                    "market_value": _safe_float(getattr(position, "market_value", None), default=0.0),
                    "avg_price": _safe_float(getattr(position, "avg_entry_price", None), default=0.0),
                    "unrealized_pl": _safe_float(getattr(position, "unrealized_pl", None), default=0.0),
                    "unrealized_pl_pct": _safe_float(getattr(position, "unrealized_plpc", None), default=0.0),
                    "current_price": _safe_float(getattr(position, "current_price", None), default=0.0)
                })
        
        return jsonify({"status": "ok", "positions": positions_data})
    except Exception as e:
        print(f"Error fetching positions: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/history", methods=["GET"])
def api_history():
    """Get portfolio history using real historical data from nav_weekly table"""
    timeframe = request.args.get('timeframe', 'ytd')
    
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Get current account information
        account = trading_client.get_account()
        current_equity = float(account.equity)
        
        # Determine start date based on timeframe
        end_date = datetime.now()
        
        if timeframe == 'all':
            # Project start date: August 25, 2025
            start_date = datetime(2025, 8, 25)
        elif timeframe == 'ytd':
            start_date = datetime(end_date.year, 1, 1)
        elif timeframe == '3m':
            start_date = end_date - timedelta(days=90)
        elif timeframe == '1m':
            start_date = end_date - timedelta(days=30)
        elif timeframe == '1w':
            start_date = end_date - timedelta(days=7)
        else:
            start_date = datetime(end_date.year, 1, 1)
        
        # Query nav_weekly table for historical data
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT week_start_date, equity 
                    FROM nav_weekly 
                    WHERE week_start_date >= %s AND week_start_date <= %s
                    ORDER BY week_start_date
                """, (start_date.date(), end_date.date()))
                
                historical_data = cur.fetchall()
        
        if not historical_data:
            return jsonify({
                "status": "error", 
                "error": f"No historical data for {timeframe}. Run: python 'ingestion/util scripts/test_nav_data.py' to check data availability."
            }), 400
        
        # Build chart data
        equity_data = []
        for date, equity in historical_data:
            equity_data.append({
                "date": date.isoformat() + "T00:00:00Z",
                "equity": round(float(equity), 2)
            })
        
        # Add current equity if not already included
        if not equity_data or equity_data[-1]["date"][:10] != end_date.date().isoformat():
            equity_data.append({
                "date": end_date.isoformat() + "Z",
                "equity": round(current_equity, 2)
            })
        
        # Calculate KPIs from actual data
        start_equity = float(historical_data[0][1])
        ytd_pl = current_equity - start_equity
        ytd_return = (ytd_pl / start_equity) * 100 if start_equity > 0 else 0
        
        return jsonify({
            "status": "ok",
            "history": equity_data,
            "kpis": {
                "start_equity": start_equity,
                "current_equity": current_equity,
                "ytd_pl": round(ytd_pl, 2),
                "ytd_return": round(ytd_return, 2)
            }
        })
        
    except psycopg2.Error as db_error:
        return jsonify({
            "status": "error", 
            "error": f"Database error: {str(db_error)}"
        }), 500
    except Exception as e:
        print(f"Error fetching portfolio history: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/history/orders", methods=["GET"])
def api_order_history():
    """Get order history"""
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Get real order history from Alpaca with pagination
        request_params = GetOrdersRequest(status=QueryOrderStatus.ALL)
        request_params.limit = 500  # Get up to 500 orders
        
        after = request.args.get('after')
        if after:
            request_params.after = after
        
        orders = trading_client.get_orders(request_params)
        
        orders_data = []
        for order in orders:
            notional = float(order.notional) if order.notional else 0
            orders_data.append({
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": float(order.qty) if order.qty else 0,
                "notional": notional,
                "status": order.status.value,
                "submitted_at": order.submitted_at.isoformat() + "Z",
                "updated_at": order.updated_at.isoformat() + "Z"
            })
        
        # Sort by notional value (biggest orders first) and take top 5
        orders_data.sort(key=lambda x: x['notional'] or 0, reverse=True)
        top_5_orders = orders_data[:5]
        
        print(f"Retrieved {len(orders_data)} total orders, showing top 5 by notional value")
        print(f"Top 5 notional values: {[order['notional'] for order in top_5_orders]}")
        return jsonify({"status": "ok", "orders": top_5_orders, "total_orders": len(orders_data)})
    except Exception as e:
        print(f"Error fetching order history: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/history/activities", methods=["GET"])
def api_activity_history():
    """Get activity history (fills, dividends, fees)"""
    types = request.args.get('types', 'FILL,DIV,FEES')
    page_size = request.args.get('page_size', 100)
    
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Try to get activities from Alpaca, but provide fallback if method doesn't exist
        activities_data = []
        
        try:
            # Check if get_activities method exists
            if hasattr(trading_client, 'get_activities'):
                activities = trading_client.get_activities()
                
                for activity in activities:
                    # Map Alpaca activity types to our format
                    activity_type = "FILL"  # Default
                    if hasattr(activity, 'activity_type'):
                        if activity.activity_type == "DIV":
                            activity_type = "DIV"
                        elif activity.activity_type == "FEE":
                            activity_type = "FEES"
                        elif activity.activity_type == "TRADE":
                            activity_type = "FILL"
                    
                    activities_data.append({
                        "id": activity.id,
                        "type": activity_type,
                        "symbol": getattr(activity, 'symbol', None),
                        "qty": int(float(activity.qty)) if hasattr(activity, 'qty') and activity.qty else None,
                        "price": float(activity.price) if hasattr(activity, 'price') and activity.price else None,
                        "time": activity.transaction_time.isoformat() + "Z",
                        "side": getattr(activity, 'side', None),
                        "net_amount": float(activity.net_amount) if hasattr(activity, 'net_amount') else 0,
                        "description": getattr(activity, 'description', None)
                    })
            else:
                # Fallback: return empty activities list with a note
                print("Warning: get_activities method not available in Alpaca SDK")
                activities_data = []
                
        except AttributeError:
            print("Warning: get_activities method not available in Alpaca SDK")
            activities_data = []
        
        # Filter activities based on query parameters
        if types != 'all':
            requested_types = [t.strip() for t in types.split(',')]
            activities_data = [activity for activity in activities_data if activity['type'] in requested_types]
        
        # Apply page size limit
        try:
            page_size_int = int(page_size)
            activities_data = activities_data[:page_size_int]
        except ValueError:
            pass  # Keep all if page_size is invalid
        
        return jsonify({"status": "ok", "activities": activities_data})
    except Exception as e:
        print(f"Error fetching activity history: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/orders", methods=["GET"])
def api_get_orders():
    """Get open orders"""
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Get real open orders from Alpaca with pagination
        request_params = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        request_params.limit = 500  # Get up to 500 orders
        orders = trading_client.get_orders(request_params)
        
        orders_data = []
        for order in orders:
            orders_data.append({
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": float(order.qty) if order.qty else 0,
                "type": order.type.value if hasattr(order, 'type') else 'market',
                "filled_qty": float(order.filled_qty) if hasattr(order, 'filled_qty') and order.filled_qty else 0,
                "filled_avg_price": float(order.filled_avg_price) if hasattr(order, 'filled_avg_price') and order.filled_avg_price else None,
                "limit_price": float(order.limit_price) if hasattr(order, 'limit_price') and order.limit_price else None,
                "notional": float(order.notional) if order.notional else None,
                "status": order.status.value,
                "submitted_at": order.submitted_at.isoformat() + "Z"
            })
        
        print(f"Retrieved {len(orders_data)} open orders from Alpaca")
        return jsonify({"status": "ok", "orders": orders_data})
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/orders/<order_id>", methods=["DELETE"])
def api_cancel_order(order_id):
    """Cancel a specific order"""
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Cancel real order in Alpaca
        trading_client.cancel_order_by_id(order_id)
        return jsonify({"status": "ok", "message": "Order cancelled successfully"})
    except Exception as e:
        print(f"Error cancelling order: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/orders", methods=["DELETE"])
def api_cancel_all_orders():
    """Cancel all open orders"""
    error_response = check_alpaca_configured()
    if error_response:
        return error_response
    
    try:
        # Cancel all real orders in Alpaca
        trading_client.cancel_all_orders()
        return jsonify({"status": "ok", "message": "All orders cancelled successfully"})
    except Exception as e:
        print(f"Error cancelling all orders: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

# ============================================================================
# LLM HELPER FUNCTIONS (Based on fetch_weekly_llm.py)
# ============================================================================

# Load LLM environment variables
LLM_KEY = os.getenv("LLM_KEY")
if not LLM_KEY:
    print("LLM_KEY not found in environment variables!")

# Mean 3-month Treasury bill yield across the experiment window (2025-08-25 to
# 2026-08-24): 249 trading days, ranging 3.62% to 4.29%. This was fetched live from FMP
# until that subscription ended. Pinning it is not a downgrade — the window is closed so
# the figure cannot change, and the average over the period is the right input for an
# annualised Sharpe anyway, where the old code was using whatever the spot rate happened
# to be on the day someone loaded the page.
RISK_FREE_RATE_ANNUAL = 0.038134

# Custom JSON encoder to handle date and decimal objects
class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        elif hasattr(obj, '__float__'):  # Handle Decimal, Fraction, etc.
            return float(obj)
        return super().default(obj)

def call_render_endpoint(prompt):
    """
    Call the Render endpoint with the prompt
    """
    if not LLM_KEY:
        return None
        
    url = "https://api.runpod.ai/v2/75lfr05y2bgbmr/run"
    headers = {
        "Authorization": f"Bearer {LLM_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "input": {
            "prompt": prompt
        },
        "sampling_params": {
            "temperature": 0,
            "top_p": 1.0,
            "max_tokens": 1024,
            "repetition_penalty": 1.0
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error calling Render endpoint: {e}")
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
        
        return default_response
        
    except Exception as e:
        print(f"Error creating default response: {e}")
        # Ultimate fallback
        return {
            "ticker": ticker,
            "snapshot": "2025-08-16",
            "verdict": "Hold",
            "new_alloc_pct": 0.0,
            "reasoning": "Failed to parse LLM response"
        }

# ============================================================================
# PORTFOLIO ANALYSIS ENDPOINT
# ============================================================================

@app.route("/portfolio-analysis", methods=["GET"])
def portfolio_analysis():
    """Get top 10 allocation differences between FMP API and LLM recommendations"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    try:
        with engine.connect() as conn:
            # Get the latest allocation data for each ticker and compare with LLM recommendations
            result = conn.execute(text("""
                WITH latest_allocations AS (
                    SELECT 
                        ticker,
                        allocation_pct as fmp_allocation_pct,
                        allocation_date,
                        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY allocation_date DESC) as rn
                    FROM allocations
                ),
                latest_llm_data AS (
                    SELECT 
                        ticker,
                        response_data->>'new_alloc_pct' as llm_allocation_pct,
                        week_start_date,
                        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY week_start_date DESC) as rn
                    FROM weekly_llm_data
                    WHERE status = 'completed' 
                    AND response_data->>'new_alloc_pct' IS NOT NULL
                )
                SELECT 
                    la.ticker,
                    la.fmp_allocation_pct,
                    lld.llm_allocation_pct::NUMERIC as llm_allocation_pct,
                    ABS(la.fmp_allocation_pct - (lld.llm_allocation_pct::NUMERIC)) as allocation_difference,
                    la.allocation_date,
                    lld.week_start_date,
                    t.company_name,
                    t.sector
                FROM latest_allocations la
                JOIN latest_llm_data lld ON la.ticker = lld.ticker
                JOIN tickers t ON la.ticker = t.ticker
                WHERE la.rn = 1 AND lld.rn = 1
                ORDER BY allocation_difference DESC
                LIMIT 10
            """))
            
            positions = []
            total_fmp_allocation = 0
            total_llm_allocation = 0
            
            for row in result.mappings():
                ticker = row['ticker']
                fmp_allocation_pct = float(row['fmp_allocation_pct'])
                llm_allocation_pct = float(row['llm_allocation_pct'])
                allocation_difference = float(row['allocation_difference'])
                allocation_date = row['allocation_date']
                week_start_date = row['week_start_date']
                company_name = row['company_name']
                sector = row['sector']
                
                # Calculate percentage difference
                percentage_diff = ((llm_allocation_pct - fmp_allocation_pct) / fmp_allocation_pct * 100) if fmp_allocation_pct > 0 else 0
                
                total_fmp_allocation += fmp_allocation_pct
                total_llm_allocation += llm_allocation_pct
                
                positions.append({
                    "ticker": ticker,
                    "company_name": company_name,
                    "sector": sector,
                    "fmp_allocation_pct": fmp_allocation_pct,
                    "llm_allocation_pct": llm_allocation_pct,
                    "allocation_difference": allocation_difference,
                    "percentage_diff": percentage_diff,
                    "allocation_date": allocation_date.isoformat() if allocation_date else None,
                    "llm_date": week_start_date.isoformat() if week_start_date else None
                })
            
            # Add ranking
            for i, position in enumerate(positions, 1):
                position["rank"] = i
            
            total_difference = total_llm_allocation - total_fmp_allocation
            
            return jsonify({
                "top_positions": positions,
                "summary": {
                    "total_positions": len(positions),
                    "total_fmp_allocation": total_fmp_allocation,
                    "total_llm_allocation": total_llm_allocation,
                    "total_difference": total_difference
                }
            })
            
    except Exception as e:
        print(f"Error in portfolio analysis: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

# ============================================================================
# PERFORMANCE STATISTICS ENDPOINTS
# ============================================================================

def calculate_performance_stats(conn, since=None, weeks=None, rf_annual=None, boots=10000):
    """
    Calculate performance statistics using the same logic as run_performance_tests.py
    Returns a dictionary with all performance metrics
    """
    import numpy as np
    import math
    from datetime import datetime, timedelta
    
    # Helper functions from run_performance_tests.py
    def pct_to_float(arr_pct):
        return np.array([float(x) / 100.0 for x in arr_pct], dtype=float)

    def cumulative_return(weekly_r):
        if weekly_r.size == 0:
            return float('nan')
        return float(np.prod(1.0 + weekly_r) - 1.0)

    def max_drawdown(weekly_r):
        if weekly_r.size == 0:
            return float('nan')
        equity = np.cumprod(1.0 + weekly_r)
        peaks = np.maximum.accumulate(equity)
        dd = (equity - peaks) / peaks
        return float(np.min(dd))

    def weekly_rf_from_annual(annual_rf):
        return (1.0 + annual_rf)**(1.0 / 52) - 1.0

    def clean(value):
        """
        Flask serialises NaN and Infinity as bare literals, which are invalid JSON
        and throw inside response.json() on the client. Emit null instead.
        """
        if value is None:
            return None
        try:
            f = float(value)
        except (TypeError, ValueError):
            return value
        return f if math.isfinite(f) else None

    def iso(d):
        return d.isoformat() if hasattr(d, 'isoformat') else str(d)

    def ttest_one_sided_mean_gt_zero(x):
        """
        Upper-tail test of H0: mean <= 0 against H1: mean > 0.

        The claim being tested is directional ("the strategy beat SPY"), so the
        tail must be too. Using abs(t) here would hand a small p-value to a
        strongly negative excess return and report it as a significant win.
        """
        x = np.asarray(x, dtype=float)
        n = x.size
        if n < 2:
            return float('nan'), 0, float('nan')
        mean = x.mean()
        sd = x.std(ddof=1)
        if sd == 0.0:
            if mean > 0:
                return math.inf, n - 1, 0.0
            return (-math.inf if mean < 0 else 0.0), n - 1, 1.0
        se = sd / math.sqrt(n)
        t_stat = mean / se
        df = n - 1
        try:
            from scipy import stats
            p = float(stats.t.sf(t_stat, df=df))
        except Exception:
            # Normal approximation: sf(t) = 0.5 * erfc(t / sqrt(2)), signed.
            p = 0.5 * math.erfc(t_stat / math.sqrt(2.0))
        return float(t_stat), df, float(p)

    def bootstrap_excess(x, iters=10000, seed=42):
        """
        Percentile CI for the mean, plus a p-value from resampling under the null.

        Resampling the observed series and counting how often the mean clears zero
        does not give a p-value, because that distribution is centred on the
        observed mean rather than on the hypothesised zero. So the sample is
        recentred before the null draw. The (count + 1) / (iters + 1) form keeps
        the result away from an impossible exact zero.

        This is an iid bootstrap: it assumes excess returns are independent across
        days. Serial correlation would make the interval narrower than it should be.
        """
        x = np.asarray(x, dtype=float)
        n = x.size
        if n < 2:
            return (float('nan'), float('nan')), float('nan'), float('nan')
        rng = np.random.default_rng(seed)
        obs_mean = float(x.mean())

        samp_means = x[rng.integers(0, n, size=(iters, n))].mean(axis=1)
        lo, hi = np.percentile(samp_means, [2.5, 97.5])
        prob_pos = float(np.mean(samp_means > 0.0))

        centred = x - obs_mean
        null_means = centred[rng.integers(0, n, size=(iters, n))].mean(axis=1)
        p_boot = (float(np.sum(null_means >= obs_mean)) + 1.0) / (iters + 1.0)

        return (float(lo), float(hi)), prob_pos, float(p_boot)

    def fetch_daily_data(conn, since, weeks):
        """Fetch daily data from nav_weekly and benchmark_weekly tables"""
        where_conditions = ["n.week_start_date >= '2025-08-25'"]
        params = {}
        
        if since:
            since_date = max('2025-08-25', since)
            where_conditions.append("n.week_start_date >= :since")
            params["since"] = since_date

        sql = f"""
            SELECT n.week_start_date as date,
                   n.equity,
                   b.adj_close
            FROM nav_weekly n
            LEFT JOIN benchmark_weekly b ON n.week_start_date = b.week_start_date AND b.symbol = 'SPY'
            WHERE n.equity IS NOT NULL AND b.adj_close IS NOT NULL
            AND {' AND '.join(where_conditions)}
            ORDER BY n.week_start_date
        """
        
        rows = conn.execute(text(sql), params).fetchall()

        if not rows or len(rows) < 2:
            return [], np.array([], dtype=float), np.array([], dtype=float)

        dates = []
        daily_returns_portfolio = []
        daily_returns_benchmark = []
        
        for i in range(1, len(rows)):
            prev_equity = float(rows[i-1][1])
            curr_equity = float(rows[i][1])
            prev_price = float(rows[i-1][2])
            curr_price = float(rows[i][2])
            
            if prev_equity > 0:
                port_return = (curr_equity - prev_equity) / prev_equity
            else:
                port_return = 0.0
                
            if prev_price > 0:
                bench_return = (curr_price - prev_price) / prev_price
            else:
                bench_return = 0.0
            
            dates.append(rows[i][0])
            daily_returns_portfolio.append(port_return)
            daily_returns_benchmark.append(bench_return)

        rp = np.array(daily_returns_portfolio, dtype=float)
        rb = np.array(daily_returns_benchmark, dtype=float)
        
        if weeks is not None and weeks > 0:
            # The series holds trading days only, so a week is 5 rows, not 7.
            days_to_keep = weeks * 5
            if len(dates) > days_to_keep:
                dates = dates[-days_to_keep:]
                rp = rp[-days_to_keep:]
                rb = rb[-days_to_keep:]

        return dates, rp, rb

    def aggregate_daily_to_weekly(dates, daily_returns_portfolio, daily_returns_benchmark):
        """Aggregate daily returns into weekly returns"""
        if len(dates) == 0:
            return [], np.array([], dtype=float), np.array([], dtype=float)
        
        weekly_data = {}
        
        for i, date in enumerate(dates):
            if isinstance(date, str):
                date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            else:
                date_obj = date
            
            monday = date_obj - timedelta(days=date_obj.weekday())
            
            if monday not in weekly_data:
                weekly_data[monday] = {
                    'dates': [],
                    'portfolio_returns': [],
                    'benchmark_returns': []
                }
            
            weekly_data[monday]['dates'].append(date)
            weekly_data[monday]['portfolio_returns'].append(daily_returns_portfolio[i])
            weekly_data[monday]['benchmark_returns'].append(daily_returns_benchmark[i])
        
        weekly_dates = []
        weekly_portfolio = []
        weekly_benchmark = []
        
        for monday in sorted(weekly_data.keys()):
            week_data = weekly_data[monday]
            
            port_weekly = cumulative_return(np.array(week_data['portfolio_returns']))
            bench_weekly = cumulative_return(np.array(week_data['benchmark_returns']))
            
            weekly_dates.append(monday)
            weekly_portfolio.append(port_weekly)
            weekly_benchmark.append(bench_weekly)
        
        return weekly_dates, np.array(weekly_portfolio), np.array(weekly_benchmark)

    if rf_annual is None:
        rf_annual = RISK_FREE_RATE_ANNUAL
    
    # Main calculation logic
    daily_dates, daily_rp, daily_rb = fetch_daily_data(conn, since, weeks)
    
    if daily_rp.size < 2:
        return {"error": "Not enough daily data to run tests (need ≥ 2 days)"}
    
    dates, rp, rb = aggregate_daily_to_weekly(daily_dates, daily_rp, daily_rb)
    
    if rp.size < 2:
        return {"error": "Not enough weekly data after aggregation (need ≥ 2 weeks)"}

    start = dates[0]
    end = dates[-1]
    n = rp.size
    rf_w = weekly_rf_from_annual(rf_annual)
    
    n_daily = daily_rp.size
    daily_excess = daily_rp - daily_rb
    excess = rp - rb
    rp_rf = rp - rf_w

    # Calculate all metrics
    mean_rp = float(rp.mean())
    std_rp = float(rp.std(ddof=1))
    mean_rb = float(rb.mean())
    std_rb = float(rb.std(ddof=1))
    mean_ex = float(excess.mean())
    std_ex = float(excess.std(ddof=1))

    sharpe_ann = (mean_rp - rf_w) / std_rp * math.sqrt(52) if std_rp > 0 else float('nan')
    sharpe_rb_ann = (mean_rb - rf_w) / std_rb * math.sqrt(52) if std_rb > 0 else float('nan')
    ir_ann = mean_ex / std_ex * math.sqrt(52) if std_ex > 0 else float('nan')

    cum_rp = cumulative_return(rp)
    cum_rb = cumulative_return(rb)
    cum_ex = cum_rp - cum_rb
    # Compounded relative return, unlike the arithmetic difference above.
    cum_ex_geo = ((1.0 + cum_rp) / (1.0 + cum_rb) - 1.0) if cum_rb != -1.0 else float('nan')

    mdd_rp = max_drawdown(rp)
    mdd_rb = max_drawdown(rb)

    win_rate = float(np.mean(excess > 0.0)) if n > 0 else float('nan')

    t_stat, df, p_val = ttest_one_sided_mean_gt_zero(excess)
    (ci_lo, ci_hi), prob_pos, p_boot = bootstrap_excess(excess, iters=boots, seed=42)

    # Daily statistics
    daily_mean_rp = float(daily_rp.mean())
    daily_std_rp = float(daily_rp.std(ddof=1))
    daily_mean_rb = float(daily_rb.mean())
    daily_std_rb = float(daily_rb.std(ddof=1))
    daily_mean_ex = float(daily_excess.mean())
    daily_std_ex = float(daily_excess.std(ddof=1))
    
    # The series contains trading days only (weekends are dropped at ingestion),
    # so both the risk-free conversion and the annualisation use 252, not 365.
    daily_rf = (1.0 + rf_annual) ** (1.0 / 252) - 1.0
    daily_sharpe_ann = (daily_mean_rp - daily_rf) / daily_std_rp * math.sqrt(252) if daily_std_rp > 0 else float('nan')
    daily_sharpe_rb_ann = (daily_mean_rb - daily_rf) / daily_std_rb * math.sqrt(252) if daily_std_rb > 0 else float('nan')
    daily_ir_ann = daily_mean_ex / daily_std_ex * math.sqrt(252) if daily_std_ex > 0 else float('nan')

    daily_t_stat, daily_df, daily_p_val = ttest_one_sided_mean_gt_zero(daily_excess)
    (daily_ci_lo, daily_ci_hi), daily_prob_pos, daily_p_boot = bootstrap_excess(
        daily_excess, iters=boots, seed=42
    )

    daily_mdd_rp = max_drawdown(daily_rp)
    daily_mdd_rb = max_drawdown(daily_rb)

    win_rate_daily = float(np.mean(daily_excess > 0.0)) if n_daily > 0 else float('nan')

    # Beta matters here because the excess series above implicitly assumes it is 1.
    var_rb = float(np.var(daily_rb, ddof=1))
    if var_rb > 0:
        beta = float(np.cov(daily_rp, daily_rb, ddof=1)[0, 1] / var_rb)
        alpha_daily = (daily_mean_rp - daily_rf) - beta * (daily_mean_rb - daily_rf)
        alpha_ann = (1.0 + alpha_daily) ** 252 - 1.0
    else:
        beta = float('nan')
        alpha_ann = float('nan')

    def point(date_value, port, bench):
        return {
            "date": iso(date_value),
            "portfolio_return": clean(port),
            "benchmark_return": clean(bench),
            "excess_return": clean(port - bench),
        }

    weekly_series = [point(dates[i], rp[i], rb[i]) for i in range(len(rp))]
    daily_series = [point(daily_dates[i], daily_rp[i], daily_rb[i]) for i in range(len(daily_rp))]

    return {
        "period": {
            "start": iso(start),
            "end": iso(end),
            "weeks": n,
            "days": n_daily
        },
        "risk_free_rate": {
            "annual": clean(rf_annual),
            "weekly": clean(rf_w),
            "daily": clean(daily_rf)
        },
        "daily_returns": {
            "portfolio": {
                "mean": clean(daily_mean_rp),
                "std": clean(daily_std_rp),
                "sharpe_annualized": clean(daily_sharpe_ann),
                "max_drawdown": clean(daily_mdd_rp)
            },
            "benchmark": {
                "mean": clean(daily_mean_rb),
                "std": clean(daily_std_rb),
                "sharpe_annualized": clean(daily_sharpe_rb_ann),
                "max_drawdown": clean(daily_mdd_rb)
            },
            "excess": {
                "mean": clean(daily_mean_ex),
                "std": clean(daily_std_ex),
                "information_ratio_annualized": clean(daily_ir_ann)
            }
        },
        "weekly_returns": {
            "portfolio": {
                "mean": clean(mean_rp),
                "std": clean(std_rp),
                "sharpe_annualized": clean(sharpe_ann),
                "max_drawdown": clean(mdd_rp)
            },
            "benchmark": {
                "mean": clean(mean_rb),
                "std": clean(std_rb),
                "sharpe_annualized": clean(sharpe_rb_ann),
                "max_drawdown": clean(mdd_rb)
            },
            "excess": {
                "mean": clean(mean_ex),
                "std": clean(std_ex),
                "information_ratio_annualized": clean(ir_ann)
            }
        },
        "cumulative_performance": {
            "portfolio": clean(cum_rp),
            "benchmark": clean(cum_rb),
            "outperformance": clean(cum_ex),
            "outperformance_compounded": clean(cum_ex_geo)
        },
        "risk": {
            "beta": clean(beta),
            "alpha_annualized": clean(alpha_ann)
        },
        "win_rate": clean(win_rate),
        "win_rate_weekly": clean(win_rate),
        "win_rate_daily": clean(win_rate_daily),
        "statistical_tests": {
            "daily": {
                "t_statistic": clean(daily_t_stat),
                "degrees_freedom": daily_df,
                "p_value": clean(daily_p_val),
                "p_value_bootstrap": clean(daily_p_boot),
                "bootstrap_ci": [clean(daily_ci_lo), clean(daily_ci_hi)],
                "probability_positive": clean(daily_prob_pos)
            },
            "weekly": {
                "t_statistic": clean(t_stat),
                "degrees_freedom": df,
                "p_value": clean(p_val),
                "p_value_bootstrap": clean(p_boot),
                "bootstrap_ci": [clean(ci_lo), clean(ci_hi)],
                "probability_positive": clean(prob_pos)
            },
            "tail": "one-sided (H1: mean excess return > 0)",
            "bootstrap_iterations": boots
        },
        "weekly_series": weekly_series,
        "daily_series": daily_series,
        "recent_performance": {
            "last_10_days": daily_series[-10:],
            "last_6_weeks": weekly_series[-6:]
        }
    }

@app.route("/api/performance/summary", methods=["GET"])
def api_performance_summary():
    """Get a comprehensive performance summary"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    try:
        # Get query parameters
        since = request.args.get('since')
        weeks = request.args.get('weeks', type=int)
        rf_annual = request.args.get('rf_annual', type=float)  # None if not provided
        boots = request.args.get('boots', 10000, type=int)
        
        with engine.connect() as conn:
            stats = calculate_performance_stats(conn, since, weeks, rf_annual, boots)
            
        if "error" in stats:
            return jsonify({"status": "error", "error": stats["error"]}), 400
            
        return jsonify({
            "status": "ok",
            "performance": stats
        })
        
    except Exception as e:
        print(f"Error calculating performance stats: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/performance/quick", methods=["GET"])
def api_performance_quick():
    """Get quick performance metrics for dashboard display"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    try:
        with engine.connect() as conn:
            stats = calculate_performance_stats(conn, since=None, weeks=4, rf_annual=None, boots=1000)
            
        if "error" in stats:
            return jsonify({"status": "error", "error": stats["error"]}), 400
        
        # Extract key metrics for quick display
        quick_stats = {
            "period": stats["period"],
            "cumulative_performance": stats["cumulative_performance"],
            "daily_returns": {
                "portfolio_mean": stats["daily_returns"]["portfolio"]["mean"],
                "benchmark_mean": stats["daily_returns"]["benchmark"]["mean"],
                "excess_mean": stats["daily_returns"]["excess"]["mean"]
            },
            "risk_metrics": {
                "portfolio_sharpe": stats["daily_returns"]["portfolio"]["sharpe_annualized"],
                "information_ratio": stats["daily_returns"]["excess"]["information_ratio_annualized"],
                "portfolio_max_dd": stats["daily_returns"]["portfolio"]["max_drawdown"],
                "benchmark_max_dd": stats["daily_returns"]["benchmark"]["max_drawdown"]
            },
            "win_rate": stats["win_rate"],
            "significance": {
                "p_value": stats["statistical_tests"]["daily"]["p_value"],
                "probability_positive": stats["statistical_tests"]["daily"]["probability_positive"]
            },
            "recent_performance": stats["recent_performance"]["last_10_days"][-5:]  # Last 5 days
        }
            
        return jsonify({
            "status": "ok",
            "quick_stats": quick_stats
        })
        
    except Exception as e:
        print(f"Error calculating quick performance stats: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/treasury-rate", methods=["GET"])
def api_treasury_rate():
    """Risk-free rate used by the performance statistics."""
    return jsonify({
        "status": "ok",
        "treasury_rate": RISK_FREE_RATE_ANNUAL,
        "treasury_rate_percent": RISK_FREE_RATE_ANNUAL * 100
    })

# ============================================================================
# LLM ENDPOINTS
# ============================================================================

@app.route("/api/stocks/<ticker>/llm-analysis", methods=["POST"])
def api_llm_analysis(ticker):
    """Send ticker data to LLM for analysis and return the raw response"""
    error_response = check_database_configured()
    if error_response:
        return error_response
    
    if not LLM_KEY:
        return jsonify({
            "status": "error", 
            "error": "LLM not configured. Set LLM_KEY environment variable."
        }), 500
    
    try:
        with engine.connect() as conn:
            # Get full data for ticker
            full_data = get_full_data_for_ticker_llm(conn, ticker)
            
            # Create prompt
            prompt = create_prompt_for_ticker(full_data)
            
            # Call Render endpoint
            response = call_render_endpoint(prompt)
            
            if response:
                # Just return the raw response
                return jsonify({
                    "status": "ok", 
                    "raw_response": response,
                    "prompt_length": len(prompt)
                })
            else:
                return jsonify({
                    "status": "error", 
                    "error": "No response from LLM service"
                }), 500
                
    except Exception as e:
        print(f"Error in LLM analysis: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
