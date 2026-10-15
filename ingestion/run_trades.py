
from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import psycopg2
import requests
from decimal import Decimal, ROUND_DOWN
from datetime import date, timedelta

"""
PORTFOLIO REBALANCING STRATEGY

What it does: Rebalances the portfolio based on the latest S&P 500 market cap-weighted allocations from the database.

STRATEGY OVERVIEW:
- Market Cap Weighted: Uses S&P 500 market cap percentages to determine target allocations
- Conservative Cash Management: Prevents negative cash using non-marginable buying power limits
- Two-Phase Execution: Sells first, then buys (doesn't assume sell proceeds are immediately available)
- Proportional Scaling: If buy orders exceed available cash, scales all buys proportionally to maintain allocation ratios

EXECUTION APPROACH:
1. Fetch latest S&P 500 allocations from database (market cap weighted percentages)
2. Get current account state (equity, cash, positions) from Alpaca
3. Calculate target position values based on current equity and allocation percentages
4. Determine required trades (buys/sells) to reach target allocations
5. Apply conservative cash management:
   - Use min(cash, non_marginable_buying_power) as safe limit
   - Add buffer (1% of cash or $50) for safety margin
   - Scale buy orders if they exceed safe cap
6. Execute in two phases:
   - Phase 1: Submit all sell orders
   - Phase 2: Submit scaled buy orders
7. Store actual allocations after rebalancing

MATHEMATICAL OPERATIONS:
- Target Value = Current Equity × Allocation Percentage
- Delta = Target Value - Current Value (positive = buy, negative = sell)
- Safe Cap = min(cash, non_marginable_buying_power) - buffer
- Scale Factor = Safe Cap / Total Buy Value (if scaling needed)
- Scaled Notional = Original Notional × Scale Factor

Data storage: Stores the actual allocations after rebalancing in the actual_portfolio_allocations table.
"""


# ── Config ─────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
ALPACA_KEY   = os.getenv("ALPACA_KEY")
ALPACA_SEC   = os.getenv("ALPACA_SECRET")
ALPACA_BASE  = os.getenv("ALPACA_HTTP_BASE", "https://paper-api.alpaca.markets")
MIN_TRADE_NOTIONAL = Decimal(os.getenv("MIN_TRADE_NOTIONAL", "5"))
DRY_RUN = os.getenv("DRY_RUN", "1") == "1"
POST_SLEEP_SECS = float(os.getenv("POST_SLEEP_SECS", "0.35"))

def convert_ticker_for_alpaca(ticker):
    """
    Convert ticker names from database format to Alpaca format
    
    WHY: Some tickers have different formats in different systems
    - Database might store "BF-B" but Alpaca expects "BF.B"
    - This ensures compatibility between our data source and trading platform
    
    KNOWN CONVERSIONS:
    - BF-B -> BF.B (Berkshire Hathaway B shares)
    - BRK-B -> BRK.B (Berkshire Hathaway B shares)
    """
    ticker_conversions = {
        "BF-B": "BF.B",
        "BRK-B": "BRK.B"
    }
    return ticker_conversions.get(ticker, ticker)

required = ("DATABASE_URL","ALPACA_KEY","ALPACA_SECRET")
missing = [k for k in required if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing required env: {', '.join(missing)}")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SEC,
    "accept": "application/json",
    "content-type": "application/json",
}

def aget(path, **kwargs):
    url = f"{ALPACA_BASE.rstrip('/')}/v2{path}"
    r = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
    if r.status_code >= 400:
        print(f"[HTTP {r.status_code}] GET {path} -> {r.text[:200]}")
    r.raise_for_status()
    return r.json()

def apost(path, payload, retries=3):
    url = f"{ALPACA_BASE.rstrip('/')}/v2{path}"
    body = json.dumps(payload)
    for attempt in range(1, retries+1):
        r = requests.post(url, headers=HEADERS, data=body, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "60"))
            print(f"[429] rate limit; sleeping {wait}s (attempt {attempt}/{retries})")
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            print(f"[HTTP {r.status_code}] POST {path} payload={payload} -> {r.text[:500]}")
            if attempt < retries:
                time.sleep(2 * attempt)
                continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()

# ── DB: latest allocations ─────────────────────────────────────────────────────
def fetch_latest_allocations():
    """
    Fetch the latest S&P 500 market cap-weighted allocations from the database
    
    STRATEGY: Uses the most recent allocation snapshot to determine target portfolio weights
    - These allocations represent the current market cap percentages of S&P 500 companies
    - We use these as our target weights for portfolio rebalancing
    
    RETURNS:
      weights_raw: dict[ticker] = Decimal(allocation_pct) - Raw allocation percentages from database
      latest_date: snapshot date - When this allocation snapshot was taken
    
    EXAMPLE:
      weights_raw = {"AAPL": 0.061234, "MSFT": 0.052345, ...}
      latest_date = 2024-01-15
    """
    sql = """
    WITH latest AS (SELECT max(allocation_date) AS d FROM allocations)
    SELECT a.ticker, a.allocation_pct, l.d
    FROM allocations a
    JOIN latest l ON a.allocation_date = l.d
    """
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        if not rows:
            raise RuntimeError("No allocations found.")
    weights = {t: Decimal(str(p)) for (t, p, _) in rows}
    latest_date = rows[0][2]
    return weights, latest_date

# ── DB: actual portfolio allocations ───────────────────────────────────────────
def store_actual_allocations(weights, equity, snap_date):
    """
    Store the actual portfolio allocations after rebalancing
    
    STRATEGY: Track what we actually achieved vs what we targeted
    - Records the real allocation percentages after all trades are executed
    - Useful for performance analysis and strategy validation
    - Helps understand slippage between target and actual allocations
    
    PARAMETERS:
      weights: dict[ticker] = Decimal(normalized_pct) - Target allocation weights used
      equity: Decimal - Total portfolio equity at rebalancing time
      snap_date: date - Allocation snapshot date (for tracking which snapshot we used)
    
    STORAGE: Saves to actual_portfolio_allocations table for historical tracking
    """
    sql = """
    INSERT INTO actual_portfolio_allocations 
    (ticker, allocation_date, actual_allocation_pct, portfolio_value, position_value)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (ticker, allocation_date) DO UPDATE SET
        actual_allocation_pct = EXCLUDED.actual_allocation_pct,
        portfolio_value = EXCLUDED.portfolio_value,
        position_value = EXCLUDED.position_value,
        created_at = NOW()
    """
    
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        for ticker, norm_pct in weights.items():
            position_value = (equity * norm_pct).quantize(Decimal("0.01"))
            cur.execute(sql, (
                ticker, 
                snap_date, 
                float(norm_pct),  # Store as decimal (0.0025 for 0.25%)
                float(equity),
                float(position_value)
            ))
        conn.commit()
    
    print(f"[store] Saved actual allocations for {len(weights)} tickers")

# ── Alpaca state ───────────────────────────────────────────────────────────────
def get_account_info():
    """
    Get account information and calculate conservative cash management limits
    
    STRATEGY: Conservative cash management to prevent negative cash situations
    - Uses non-marginable buying power as the most conservative limit
    - Adds safety buffer to account for market fluctuations and fees
    - Ensures we never exceed our actual available cash
    
    CASH MANAGEMENT CALCULATIONS:
    1. Safe Cash Limit = min(cash, non_marginable_buying_power)
       - Uses the more conservative of the two values
       - non_marginable_buying_power represents cash-only buying capacity
    
    2. Buffer = min(cash * 1%, $50)
       - Safety margin to account for market movements and fees
       - Uses 1% of cash or $50, whichever is smaller
    
    3. Safe Cap = max(0, safe_cash_limit - buffer)
       - Final conservative limit for buy orders
       - Ensures we always have some cash buffer remaining
    
    RETURNS: dict with account info and calculated safe limits
    """
    acct = aget("/account")  # includes 'equity', 'cash', 'buying_power', 'non_marginable_buying_power'
    eq = Decimal(str(acct["equity"]))
    cash = Decimal(str(acct.get("cash", "0")))
    buying_power = Decimal(str(acct.get("buying_power", "0")))
    non_marginable_buying_power = Decimal(str(acct.get("non_marginable_buying_power", "0")))
    
    # Cash-based limit: Use cash as primary limit when it's significantly higher than non_marginable_buying_power
    # This handles cases where Alpaca's non_marginable_buying_power is artificially low
    if cash > non_marginable_buying_power * Decimal("1.5"):
        safe_cash_limit = cash
        print(f"[cash_management] Using cash as limit (${cash:,}) - non_marginable_buying_power (${non_marginable_buying_power:,}) appears artificially low")
    else:
        safe_cash_limit = min(cash, non_marginable_buying_power if non_marginable_buying_power > 0 else cash)
        print(f"[cash_management] Using conservative limit (${safe_cash_limit:,})")
    
    # Add buffer (1% of cash or $50, whichever is smaller)
    buffer = min(cash * Decimal("0.01"), Decimal("50"))
    safe_cap = max(Decimal("0"), safe_cash_limit - buffer)
    
    print(f"[account] equity=${eq:,}  cash=${cash:,}  buying_power=${buying_power:,}  non_marginable=${non_marginable_buying_power:,}")
    print(f"[cash_management] safe_cash_limit=${safe_cash_limit:,}  buffer=${buffer:,}  safe_cap=${safe_cap:,}")
    
    # Warn if cash is negative
    if cash < 0:
        print(f"[WARNING] Cash is negative: ${cash:,}. This may cause issues with buy orders.")
    
    return {
        "equity": eq,
        "cash": cash,
        "buying_power": buying_power,
        "non_marginable_buying_power": non_marginable_buying_power,
        "safe_cap": safe_cap
    }

def positions_value_map():
    """
    Get current portfolio positions and their market values
    
    STRATEGY: Understand current portfolio state before rebalancing
    - Maps each ticker to its current market value in the portfolio
    - Only includes open positions (closed positions won't appear)
    - Used to calculate deltas (target vs current) for each position
    
    RETURNS: dict[symbol] = Decimal(market_value)
    - symbol: ticker symbol (e.g., "AAPL")
    - market_value: current market value of the position in dollars
    
    EXAMPLE: {"AAPL": 5000.00, "MSFT": 3000.00, "GOOGL": 2000.00}
    
    NOTE: Alpaca returns only open positions; closed symbols won't appear in the dict
    """
    pos = aget("/positions")
    out = {p["symbol"]: Decimal(p.get("market_value","0") or "0") for p in pos}
    print(f"[positions] open={len(out)}  sample={list(out)[:8]}")
    return out

# ── Rebalance ──────────────────────────────────────────────────────────────────
def main():
    """
    MAIN REBALANCING EXECUTION FUNCTION
    
    STRATEGY EXECUTION FLOW:
    1. Fetch latest S&P 500 allocations (market cap weighted percentages)
    2. Get current account state (equity, cash, positions)
    3. Normalize allocation weights to sum to 100%
    4. Calculate target position values based on current equity
    5. Determine required trades (buys/sells) to reach targets
    6. Apply conservative cash management and scaling
    7. Execute trades in two phases (sells first, then buys)
    8. Store actual allocations for tracking
    """
    print("== Rebalance start ==")
    print(f"[env] base={ALPACA_BASE}  dry_run={DRY_RUN}  min_trade=${MIN_TRADE_NOTIONAL}  sleep={POST_SLEEP_SECS}s")

    # STEP 1: Fetch latest S&P 500 market cap-weighted allocations
    weights_raw, snap_date = fetch_latest_allocations()
    print(f"[db] latest allocation_date={snap_date}  tickers={len(weights_raw)}")
    
    # STEP 2: Validate and normalize allocation weights
    sum_all = sum(weights_raw.values())
    pos_items = {t: w for t, w in weights_raw.items() if w > 0}
    sum_pos = sum(pos_items.values())
    print(f"[db] sum(weights ALL)={sum_all:.10f}  sum(>0)={sum_pos:.10f}")
    if sum_pos <= 0:
        raise RuntimeError("Positive allocation weights sum to 0.")

    # STEP 3: Normalize positive weights to sum to 100%
    # WHY: Raw allocations might not sum to exactly 100%, so we normalize
    # This ensures our target allocations are proportional to the S&P 500 weights
    weights = {t: (w / sum_pos) for t, w in pos_items.items()}
    print(f"[normalize] positive tickers={len(weights)}  sum(normalized)={sum(weights.values()):.10f}")

    # STEP 4: Get current account state and calculate conservative cash limits
    account_info = get_account_info()
    equity = account_info["equity"]
    cash = account_info["cash"]
    buying_power = account_info["buying_power"]
    safe_cap = account_info["safe_cap"]
    
    # STEP 5: Get current portfolio positions
    cur_vals = positions_value_map()

    # STEP 6: Define universe of symbols to process
    # Universe = tickers that should have target (weights keys) OR are currently held (sell down if 0 target)
    # WHY: We need to process both target allocations and current positions
    # - Target allocations: stocks we want to buy
    # - Current positions: stocks we might need to sell (if target is 0 or reduced)
    symbols = sorted(set(weights) | set(cur_vals))
    print(f"[universe] symbols_to_process={len(symbols)}")

    # STEP 7: Initialize order tracking for two-phase execution
    # Two-phase approach: sells first, then buys
    # WHY: Don't assume sell proceeds are immediately available for buys
    sell_orders = []
    buy_orders = []
    skipped_small = 0
    total_target_value = Decimal("0")  # Track total target portfolio value
    total_current_value = Decimal("0")  # Track total current portfolio value
    total_buy_value = Decimal("0")  # Track total buy value for cash management
    
    # STEP 8: Calculate target values and required trades for each symbol
    for idx, sym in enumerate(symbols, 1):
        # Calculate target position value based on current equity and allocation percentage
        # FORMULA: Target Value = Current Equity × Allocation Percentage
        tgt_val = (equity * weights.get(sym, Decimal("0"))).quantize(Decimal("0.01"))
        
        # Get current position value (0 if not held)
        cur_val = cur_vals.get(sym, Decimal("0")).quantize(Decimal("0.01"))
        
        # Calculate required trade amount (positive = buy, negative = sell)
        # FORMULA: Delta = Target Value - Current Value
        delta = tgt_val - cur_val
        
        # Track totals for verification and reporting
        total_target_value += tgt_val
        total_current_value += cur_val
        
        # Calculate percentages for reporting and debugging
        raw_pct = weights_raw.get(sym, 0)      # Raw allocation from database
        norm_pct = weights.get(sym, 0)         # Normalized allocation weight
        cur_pct = (cur_val / equity * 100) if equity > 0 else 0    # Current portfolio percentage
        tgt_pct = (tgt_val / equity * 100) if equity > 0 else 0    # Target portfolio percentage

        if delta.copy_abs() < MIN_TRADE_NOTIONAL:
            # print(f"[{idx:03d}/{len(symbols)}][skip<min] {sym}  raw_pct={raw_pct:.4f}%  norm_pct={norm_pct:.4f}  cur_pct={cur_pct:.2f}%  cur=${cur_val}  tgt=${tgt_val}  tgt_pct={tgt_pct:.2f}%  Δ=${delta}")
            skipped_small += 1
            continue

        # STEP 9: Determine trade type and create order objects
        if delta > 0:
            # BUY ORDER: Need to increase position
            # Collect for scaling later (don't assume we have unlimited cash)
            notional = delta
            total_buy_value += notional
            
            # Convert ticker name for Alpaca if needed
            alpaca_symbol = convert_ticker_for_alpaca(sym)
            if alpaca_symbol != sym:
                print(f" Converting ticker: {sym} -> {alpaca_symbol}")
            
            # Create buy order object with metadata for scaling calculations
            od = {
                "symbol": alpaca_symbol,
                "side": "buy",
                "type": "market",
                "time_in_force": "day",       # fractional/notional orders require DAY
                "notional": float(notional),  # dollars
                # Store metadata for scaling and reporting
                "raw_pct": raw_pct,
                "norm_pct": norm_pct,
                "cur_pct": cur_pct,
                "tgt_pct": tgt_pct,
                "cur_val": cur_val,
                "tgt_val": tgt_val,
                "delta": delta
            }
            buy_orders.append(od)
            
        else:
            # SELL ORDER: Need to decrease position
            # Submit immediately (don't assume proceeds are available for buys)
            side = "sell"
            # Cap sell amount by current position value to avoid shorting
            notional = min(delta.copy_abs(), cur_val)  # avoid shorting; cap by long value

            notional = notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if notional < MIN_TRADE_NOTIONAL:
                # Skip trades below minimum threshold
                # print(f"[{idx:03d}/{len(symbols)}][skip<min-cap] {sym}  raw_pct={raw_pct:.4f}%  norm_pct={norm_pct:.4f}  Δ→${notional}")
                skipped_small += 1
                continue

            # Convert ticker name for Alpaca if needed
            alpaca_symbol = convert_ticker_for_alpaca(sym)
            if alpaca_symbol != sym:
                print(f" Converting ticker: {sym} -> {alpaca_symbol}")
            
            # Create sell order object
            od = {
                "symbol": alpaca_symbol,
                "side": side,
                "type": "market",
                "time_in_force": "day",       # fractional/notional orders require DAY
                "notional": float(notional),  # dollars
            }
            sell_orders.append(od)

    # STEP 10: Apply conservative cash management and scaling
    print(f"[plan] sell_orders={len(sell_orders)}  buy_orders={len(buy_orders)}  skipped_small={skipped_small}")
    
    # Scale buy orders if they exceed safe cap
    # STRATEGY: Proportional scaling maintains allocation ratios while staying within cash limits
    scaled_buy_orders = []
    if buy_orders and total_buy_value > safe_cap:
        # Calculate scale factor to fit all buys within safe cap
        # FORMULA: Scale Factor = Safe Cap / Total Buy Value
        scale_factor = safe_cap / total_buy_value
        print(f"[scaling] Total buy value (${total_buy_value:,.2f}) exceeds safe cap (${safe_cap:,.2f})")
        print(f"[scaling] Scaling all buy orders by factor: {scale_factor:.4f}")
        
        # Apply scaling to each buy order proportionally
        for order in buy_orders:
            original_notional = order["notional"]
            # FORMULA: Scaled Notional = Original Notional × Scale Factor
            scaled_notional = Decimal(str(original_notional)) * scale_factor
            scaled_notional = scaled_notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            
            # Only include orders that meet minimum trade size after scaling
            if scaled_notional >= MIN_TRADE_NOTIONAL:
                scaled_order = order.copy()
                scaled_order["notional"] = float(scaled_notional)
                scaled_buy_orders.append(scaled_order)
                print(f"[scaling] {order['symbol']}: ${original_notional:,.2f} -> ${scaled_notional:,.2f}")
            else:
                print(f"[scaling] {order['symbol']}: ${original_notional:,.2f} -> ${scaled_notional:,.2f} (below min trade, skipping)")
    else:
        # No scaling needed - all buy orders fit within safe cap
        scaled_buy_orders = buy_orders
        if buy_orders:
            print(f"[info] Total buy value (${total_buy_value:,.2f}) is within safe cap (${safe_cap:,.2f})")
    
    # STEP 11: Prepare final order list for execution
    # Combine orders: sells first, then scaled buys
    # WHY: Two-phase execution - don't assume sell proceeds are immediately available
    to_submit = sell_orders + scaled_buy_orders
    
    # STEP 12: Verification and reporting
    # Add verification summary to validate our calculations
    print(f"\n[VERIFICATION] Portfolio Summary:")
    print(f"  Account Equity: ${equity:,.2f}")
    print(f"  Current Cash: ${cash:,.2f}")
    print(f"  Non-Marginable Buying Power: ${account_info['non_marginable_buying_power']:,.2f}")
    print(f"  Safe Cap (Conservative): ${safe_cap:,.2f}")
    print(f"  Total Current Value: ${total_current_value:,.2f} ({total_current_value/equity*100:.2f}%)")
    print(f"  Total Target Value: ${total_target_value:,.2f} ({total_target_value/equity*100:.2f}%)")
    print(f"  Total Buy Value (Original): ${total_buy_value:,.2f}")
    print(f"  Total Buy Value (After Scaling): ${sum(Decimal(str(order['notional'])) for order in scaled_buy_orders):,.2f}")
    print(f"  Cash/Unallocated: ${equity - total_target_value:,.2f} ({(equity - total_target_value)/equity*100:.2f}%)")
    
    # Verify target percentages sum to 100%
    # VALIDATION: Ensure our normalized weights are mathematically correct
    target_pct_sum = sum((equity * weights.get(sym, Decimal("0"))).quantize(Decimal("0.01")) / equity * 100 for sym in weights)
    print(f"  Sum of Target Percentages: {target_pct_sum:.2f}%")
    
    if abs(target_pct_sum - Decimal("100.0")) > Decimal("0.01"):
        print(f" WARNING: Target percentages don't sum to 100% (off by {target_pct_sum - Decimal('100.0'):.2f}%)")
    else:
        print(f" Target percentages sum to 100% correctly")

    # STEP 13: Execute trades (or preview in dry-run mode)
    if DRY_RUN:
        # DRY RUN: Show what would be executed without actually submitting orders
        # Useful for testing and validation before live execution
        print(json.dumps(to_submit[:10], indent=2))
        print("DRY_RUN=1 -> Preview only. No orders were sent.")
        return

    # STEP 14: Execute trades in two phases
    ok, fail = 0, 0
    failed_orders = []
    
    # PHASE 1: Submit sell orders first
    # STRATEGY: Don't assume sell proceeds are immediately available for buys
    # This ensures we don't exceed our actual cash limits
    if sell_orders:
        print(f"\n[phase1] Submitting {len(sell_orders)} sell orders...")
        for i, od in enumerate(sell_orders, 1):
            try:
                resp = apost("/orders", od)
                print(f"[sell {i}/{len(sell_orders)}] {od['symbol']} {od['side']} ${od['notional']} -> {resp.get('status')} id={resp.get('id')}")
                ok += 1
            except requests.HTTPError as e:
                msg = e.response.text if e.response is not None else str(e)
                print(f"[ERROR] {od['symbol']} {od['side']} ${od['notional']} -> {msg[:200]}")
                failed_orders.append({
                    'symbol': od['symbol'],
                    'side': od['side'],
                    'notional': od['notional'],
                    'error': msg[:200]
                })
                fail += 1
            time.sleep(POST_SLEEP_SECS)  # be kind to the API
    
    # PHASE 2: Submit scaled buy orders
    # STRATEGY: Use conservative cash limits and proportional scaling
    # This ensures we maintain allocation ratios while staying within cash constraints
    if scaled_buy_orders:
        print(f"\n[phase2] Submitting {len(scaled_buy_orders)} scaled buy orders...")
        for i, od in enumerate(scaled_buy_orders, 1):
            # Clean up order object (remove extra fields used for scaling)
            # WHY: Alpaca API only needs basic order fields, not our metadata
            clean_order = {
                "symbol": od["symbol"],
                "side": od["side"],
                "type": od["type"],
                "time_in_force": od["time_in_force"],
                "notional": od["notional"]
            }
            
            try:
                resp = apost("/orders", clean_order)
                print(f"[buy {i}/{len(scaled_buy_orders)}] {od['symbol']} {od['side']} ${od['notional']} -> {resp.get('status')} id={resp.get('id')}")
                ok += 1
            except requests.HTTPError as e:
                msg = e.response.text if e.response is not None else str(e)
                print(f"[ERROR] {od['symbol']} {od['side']} ${od['notional']} -> {msg[:200]}")
                failed_orders.append({
                    'symbol': od['symbol'],
                    'side': od['side'],
                    'notional': od['notional'],
                    'error': msg[:200]
                })
                fail += 1
            time.sleep(POST_SLEEP_SECS)  # be kind to the API

    # STEP 15: Final reporting and data storage
    print(f"[done] submitted={ok}  failed={fail}  skipped={skipped_small}")
    
    # Store actual allocations after rebalancing for historical tracking
    # WHY: Track what we actually achieved vs what we targeted for performance analysis
    if not DRY_RUN:
        store_actual_allocations(weights, equity, snap_date)
    
    print("== Rebalance end ==")
    
    return failed_orders

def fetch(from_date=None, limit=None):
    """
    Wrapper function to make run_trades compatible with run_all.py
    
    STRATEGY: Integration point for automated execution
    - Allows this script to be called from the main ingestion pipeline
    - Ignores from_date and limit parameters since this is a trading script, not a data fetch
    - Returns failed orders for tracking and debugging
    
    PARAMETERS:
      from_date: Ignored (trading script doesn't fetch historical data)
      limit: Ignored (trading script doesn't limit data)
    
    RETURNS: List of failed orders for tracking and debugging
    """
    print("Starting portfolio rebalancing...")
    return main()

if __name__ == "__main__":
    try:
        main()
        
        # Log successful execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("run_trades.py", True)
        
    except Exception as e:
        # Log failed execution
        from weekly_stats_manager import log_script_execution
        log_script_execution("run_trades.py", False, str(e))
        raise