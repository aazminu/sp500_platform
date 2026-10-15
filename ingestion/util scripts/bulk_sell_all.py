from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import requests
from decimal import Decimal, ROUND_DOWN

"""
What it does: Sells all current positions to get a clean slate for portfolio rebalancing.
How it works: Fetches all current positions from Alpaca and submits market sell orders for each.
Use case: When you want to start fresh with a new allocation strategy.
"""
load_dotenv(override=True)

# ── Config ─────────────────────────────────────────────────────────────────────
ALPACA_KEY   = os.getenv("ALPACA_KEY")
ALPACA_SEC   = os.getenv("ALPACA_SECRET")
ALPACA_BASE  = os.getenv("ALPACA_HTTP_BASE", "https://paper-api.alpaca.markets")
DRY_RUN = False
POST_SLEEP_SECS = float(os.getenv("POST_SLEEP_SECS", "0.35"))

required = ("ALPACA_KEY","ALPACA_SECRET")
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

def get_account_info():
    """Get account information including cash and equity"""
    acct = aget("/account")
    cash = Decimal(str(acct.get("cash", "0")))
    equity = Decimal(str(acct.get("equity", "0")))
    buying_power = Decimal(str(acct.get("buying_power", "0")))
    
    print(f"[account] equity=${equity:,}  cash=${cash:,}  buying_power=${buying_power:,}")
    return {
        "cash": cash,
        "equity": equity,
        "buying_power": buying_power
    }

def get_all_positions():
    """Get all current positions"""
    pos = aget("/positions")
    positions = []
    total_value = Decimal("0")
    
    for p in pos:
        qty = Decimal(str(p.get("qty", "0")))
        market_value = Decimal(str(p.get("market_value", "0")))
        symbol = p.get("symbol", "")
        
        if qty > 0:  # Only include long positions
            positions.append({
                "symbol": symbol,
                "qty": qty,
                "market_value": market_value
            })
            total_value += market_value
    
    print(f"[positions] found {len(positions)} positions with total value=${total_value:,}")
    return positions, total_value

def main():
    print("== Bulk Sell All Positions ==")
    print(f"[env] base={ALPACA_BASE}  dry_run={DRY_RUN}  sleep={POST_SLEEP_SECS}s")
    
    # Get account info
    account_info = get_account_info()
    
    # Get all positions
    positions, total_position_value = get_all_positions()
    
    if not positions:
        print("[info] No positions to sell. Portfolio is already clean.")
        return
    
    print(f"\n[summary] About to sell {len(positions)} positions:")
    print(f"  Total position value: ${total_position_value:,.2f}")
    print(f"  Current cash: ${account_info['cash']:,.2f}")
    print(f"  Expected cash after sell: ${account_info['cash'] + total_position_value:,.2f}")
    
    if DRY_RUN:
        print("\n[DRY_RUN] Would submit the following sell orders:")
        for pos in positions:
            print(f"  SELL {pos['symbol']}: {pos['qty']} shares (${pos['market_value']:,.2f})")
        print("\nDRY_RUN=1 -> Preview only. No orders were sent.")
        return
    
    # Confirm before proceeding (only in non-dry-run mode)
    print(f"\n[WARNING] This will sell ALL {len(positions)} positions!")
    print("Are you sure you want to proceed? (y/N): ", end="")
    
    try:
        response = input().strip().lower()
        if response not in ['y', 'yes']:
            print("Operation cancelled.")
            return
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return
    
    # Submit sell orders
    print(f"\n[executing] Submitting {len(positions)} sell orders...")
    
    ok, fail = 0, 0
    failed_orders = []
    
    for i, pos in enumerate(positions, 1):
        try:
            # Submit market sell order for entire position
            order_payload = {
                "symbol": pos["symbol"],
                "side": "sell",
                "type": "market",
                "time_in_force": "day",
                "qty": str(pos["qty"])  # Use quantity instead of notional for sells
            }
            
            resp = apost("/orders", order_payload)
            print(f"[{i:03d}/{len(positions)}] SELL {pos['symbol']} {pos['qty']} shares -> {resp.get('status')} id={resp.get('id')}")
            ok += 1
            
        except requests.HTTPError as e:
            msg = e.response.text if e.response is not None else str(e)
            print(f"[ERROR] {pos['symbol']} SELL {pos['qty']} shares -> {msg[:200]}")
            failed_orders.append({
                'symbol': pos['symbol'],
                'qty': pos['qty'],
                'error': msg[:200]
            })
            fail += 1
        
        time.sleep(POST_SLEEP_SECS)  # be kind to the API
    
    print(f"\n[done] submitted={ok}  failed={fail}")
    
    if failed_orders:
        print(f"\n[failed_orders] {len(failed_orders)} orders failed:")
        for order in failed_orders:
            print(f"  {order['symbol']}: {order['error']}")
    
    if ok > 0:
        print(f"\n[success] Successfully submitted {ok} sell orders.")
        print("Check your Alpaca dashboard to monitor order execution.")
        print("Once all orders are filled, you can run your rebalancing script.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")
        raise
