#!/usr/bin/env python3
import os, math, datetime as dt
from decimal import Decimal
from typing import Optional, Sequence

import numpy as np
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# -------------------------- Config --------------------------
# Load .env from current directory (util scripts folder)
load_dotenv()

DB_URL = os.getenv("DATABASE_URL")  # e.g., postgres://user:pass@host:5432/dbname
if not DB_URL:
    raise SystemExit("Missing DATABASE_URL")

ANNUAL_WEEKS = 52

# ---------------------- Helper functions --------------------
def pct_to_float(arr_pct: Sequence[Decimal]) -> np.ndarray:
    """Convert percent values (e.g., 1.23) to float returns (0.0123)."""
    return np.array([float(x) / 100.0 for x in arr_pct], dtype=float)

def cumulative_return(weekly_r: np.ndarray) -> float:
    """(1+r1)*(1+r2)*... - 1"""
    if weekly_r.size == 0:
        return float('nan')
    return float(np.prod(1.0 + weekly_r) - 1.0)

def max_drawdown(weekly_r: np.ndarray) -> float:
    """Max drawdown from weekly returns."""
    if weekly_r.size == 0:
        return float('nan')
    equity = np.cumprod(1.0 + weekly_r)
    peaks = np.maximum.accumulate(equity)
    dd = (equity - peaks) / peaks
    return float(np.min(dd))  # negative value

def weekly_rf_from_annual(annual_rf: float) -> float:
    """Convert annual RF to weekly effective rate."""
    return (1.0 + annual_rf)**(1.0 / ANNUAL_WEEKS) - 1.0

def ttest_two_sided_mean_gt_zero(x: np.ndarray):
    """
    One-sample t-test on mean(x) vs 0. Returns (t_stat, df, p_value).
    Uses SciPy if available; otherwise normal approximation for p (ok when n is moderate/large).
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 2:
        return float('nan'), 0, float('nan')

    mean = x.mean()
    sd = x.std(ddof=1)
    if sd == 0.0:
        # No variability; if mean != 0, t is infinite; handle gracefully
        t_stat = math.inf if mean > 0 else (-math.inf if mean < 0 else 0.0)
        p = 0.0 if math.isfinite(t_stat) else 1.0
        return t_stat, n - 1, p

    se = sd / math.sqrt(n)
    t_stat = mean / se
    df = n - 1

    # Try SciPy for exact Student-t p-value
    try:
        from scipy import stats
        p = 2.0 * stats.t.sf(abs(t_stat), df=df)
        return float(t_stat), df, float(p)
    except Exception:
        # Normal approx fallback
        # Phi(z) via erf: Phi(z) = 0.5*(1+erf(z/sqrt(2)))
        z = abs(t_stat)
        p_one_side = 0.5 * math.erfc(z / math.sqrt(2.0))
        p_two = 2.0 * p_one_side
        return float(t_stat), df, float(p_two)

def bootstrap_mean_ci(x: np.ndarray, iters: int = 10000, seed: int = 42):
    """
    Bootstrap 95% CI for the mean of x. Also returns Pr(mean>0).
    """
    rng = np.random.default_rng(seed)
    n = x.size
    if n == 0:
        return (float('nan'), float('nan')), float('nan')
    idx = rng.integers(0, n, size=(iters, n))
    samp_means = x[idx].mean(axis=1)
    lo, hi = np.percentile(samp_means, [2.5, 97.5])
    prob_pos = float(np.mean(samp_means > 0.0))
    return (float(lo), float(hi)), prob_pos

def fmt_pct(x: Optional[float], nd=2, sign=False) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    # Convert to float if it's a Decimal
    if hasattr(x, '__float__'):
        x = float(x)
    s = f"{100.0 * x:.{nd}f}%"
    return f"{'+' if sign and x>=0 else ''}{s}"

def fmt_num(x: Optional[float], nd=4, sign=False) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    # Convert to float if it's a Decimal
    if hasattr(x, '__float__'):
        x = float(x)
    s = f"{x:.{nd}f}"
    return f"{'+' if sign and x>=0 else ''}{s}"

# ------------------------ Main logic ------------------------
def fetch_daily_data(engine, since: Optional[str], weeks: Optional[int]):
    """
    Fetches daily data from nav_weekly and benchmark_weekly tables.
    Returns (dates, rp, rb) where rp, rb are float daily returns (0.0123 = 1.23%).
    """
    # Build date filter - exclude data before model start (8-25)
    where_conditions = ["n.week_start_date >= '2025-08-25'"]  # Model started 8-25
    params = {}
    
    if since:
        # Use the later of the two dates
        since_date = max('2025-08-25', since)
        where_conditions.append("n.week_start_date >= :since")
        params["since"] = since_date

    # Join nav_weekly with benchmark_weekly to get daily data
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
    
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    if not rows or len(rows) < 2:
        return [], np.array([], dtype=float), np.array([], dtype=float)

    # Convert to daily returns
    dates = []
    daily_returns_portfolio = []
    daily_returns_benchmark = []
    
    for i in range(1, len(rows)):  # Start from second row to calculate returns
        prev_equity = float(rows[i-1][1])
        curr_equity = float(rows[i][1])
        prev_price = float(rows[i-1][2])
        curr_price = float(rows[i][2])
        
        # Calculate daily returns
        if prev_equity > 0:
            port_return = (curr_equity - prev_equity) / prev_equity
        else:
            port_return = 0.0
            
        if prev_price > 0:
            bench_return = (curr_price - prev_price) / prev_price
        else:
            bench_return = 0.0
        
        dates.append(rows[i][0])  # Current date
        daily_returns_portfolio.append(port_return)
        daily_returns_benchmark.append(bench_return)

    # Convert to numpy arrays
    rp = np.array(daily_returns_portfolio, dtype=float)
    rb = np.array(daily_returns_benchmark, dtype=float)
    
    # Optionally keep only the last N weeks of data
    if weeks is not None and weeks > 0:
        # Calculate how many days to keep (approximately 7 days per week)
        days_to_keep = weeks * 7
        if len(dates) > days_to_keep:
            dates = dates[-days_to_keep:]
            rp = rp[-days_to_keep:]
            rb = rb[-days_to_keep:]

    return dates, rp, rb

def aggregate_daily_to_weekly(dates, daily_returns_portfolio, daily_returns_benchmark):
    """
    Aggregates daily returns into weekly returns.
    Returns (weekly_dates, weekly_portfolio, weekly_benchmark) where each week is Monday to Sunday.
    """
    if len(dates) == 0:
        return [], np.array([], dtype=float), np.array([], dtype=float)
    
    # Group by week (Monday to Sunday)
    weekly_data = {}
    
    for i, date in enumerate(dates):
        # Get Monday of the week for this date
        if isinstance(date, str):
            date_obj = dt.datetime.strptime(date, '%Y-%m-%d').date()
        else:
            date_obj = date
        
        # Calculate Monday of the week
        monday = date_obj - dt.timedelta(days=date_obj.weekday())
        
        if monday not in weekly_data:
            weekly_data[monday] = {
                'dates': [],
                'portfolio_returns': [],
                'benchmark_returns': []
            }
        
        weekly_data[monday]['dates'].append(date)
        weekly_data[monday]['portfolio_returns'].append(daily_returns_portfolio[i])
        weekly_data[monday]['benchmark_returns'].append(daily_returns_benchmark[i])
    
    # Calculate weekly returns from daily returns
    weekly_dates = []
    weekly_portfolio = []
    weekly_benchmark = []
    
    for monday in sorted(weekly_data.keys()):
        week_data = weekly_data[monday]
        
        # Calculate weekly return: (1 + r1) * (1 + r2) * ... - 1
        port_weekly = cumulative_return(np.array(week_data['portfolio_returns']))
        bench_weekly = cumulative_return(np.array(week_data['benchmark_returns']))
        
        weekly_dates.append(monday)
        weekly_portfolio.append(port_weekly)
        weekly_benchmark.append(bench_weekly)
    
    return weekly_dates, np.array(weekly_portfolio), np.array(weekly_benchmark)

def fetch_simple_cumulative(engine, start_date: str, end_date: str):
    """
    Fetches portfolio values at the start and end dates and computes
    simple cumulative return = (end - start)/start
    Uses nav_weekly table which contains equity values
    """
    sql = text("""
        SELECT week_start_date, equity
        FROM nav_weekly
        WHERE week_start_date BETWEEN :start AND :end
        ORDER BY week_start_date ASC
    """)
    with engine.begin() as conn:
        rows = conn.execute(sql, {"start": start_date, "end": end_date}).fetchall()

    if not rows or len(rows) < 2:
        return float('nan')

    # Convert Decimal to float to avoid type issues
    start_val = float(rows[0][1]) if rows[0][1] is not None else 0.0
    end_val = float(rows[-1][1]) if rows[-1][1] is not None else 0.0
    
    # Avoid division by zero
    if start_val == 0:
        return float('nan')
    
    return (end_val - start_val) / start_val

def run_report(since: Optional[str], weeks: Optional[int], rf_annual: float, boots: int):
    engine = create_engine(DB_URL, pool_pre_ping=True)
    
    # Fetch daily data
    daily_dates, daily_rp, daily_rb = fetch_daily_data(engine, since, weeks)
    
    if daily_rp.size < 2:
        print("❗ Not enough daily data to run tests (need ≥ 2 days).")
        return 1
    
    # Aggregate daily data to weekly
    dates, rp, rb = aggregate_daily_to_weekly(daily_dates, daily_rp, daily_rb)
    
    if rp.size < 2:
        print("❗ Not enough weekly data after aggregation (need ≥ 2 weeks).")
        return 1

    start = dates[0]
    end = dates[-1]
    n = rp.size
    rf_w = weekly_rf_from_annual(rf_annual)
    
    # Also calculate daily statistics for better sample size
    n_daily = daily_rp.size
    daily_excess = daily_rp - daily_rb

    excess = rp - rb
    rp_rf = rp - rf_w

    # Means & stds (weekly)
    mean_rp = float(rp.mean())
    std_rp  = float(rp.std(ddof=1))
    mean_rb = float(rb.mean())
    std_rb  = float(rb.std(ddof=1))
    mean_ex = float(excess.mean())
    std_ex  = float(excess.std(ddof=1))

    # Annualized Sharpe (portfolio) & Info Ratio
    sharpe_ann = (mean_rp - rf_w) / std_rp * math.sqrt(ANNUAL_WEEKS) if std_rp > 0 else float('nan')
    ir_ann     = mean_ex / std_ex * math.sqrt(ANNUAL_WEEKS) if std_ex > 0 else float('nan')

    # Cumulative returns
    cum_rp = cumulative_return(rp)
    cum_rb = cumulative_return(rb)
    cum_ex = cum_rp - cum_rb  # not exactly equal to cum(1+excess)-1, but this is the intuitive “since start” outperformance

    # Drawdowns
    mdd_rp = max_drawdown(rp)
    mdd_rb = max_drawdown(rb)

    # Win rate vs SPY
    win_rate = float(np.mean(excess > 0.0)) if n > 0 else float('nan')

    # Paired t-test on weekly excess
    t_stat, df, p_val = ttest_two_sided_mean_gt_zero(excess)

    # Bootstrap CI on mean weekly excess
    (ci_lo, ci_hi), prob_pos = bootstrap_mean_ci(excess, iters=boots, seed=42)

    # Calculate daily statistics for better sample size
    daily_mean_rp = float(daily_rp.mean())
    daily_std_rp = float(daily_rp.std(ddof=1))
    daily_mean_rb = float(daily_rb.mean())
    daily_std_rb = float(daily_rb.std(ddof=1))
    daily_mean_ex = float(daily_excess.mean())
    daily_std_ex = float(daily_excess.std(ddof=1))
    
    # Annualized Sharpe from daily data
    daily_rf = rf_annual / 365  # Daily risk-free rate
    daily_sharpe_ann = (daily_mean_rp - daily_rf) / daily_std_rp * math.sqrt(365) if daily_std_rp > 0 else float('nan')
    daily_ir_ann = daily_mean_ex / daily_std_ex * math.sqrt(365) if daily_std_ex > 0 else float('nan')

    # Pretty print
    print("\n================ OracleZero Performance Report ================\n")
    print(f"Range: {start} → {end}  (weeks: {n}, days: {n_daily})")
    print(f"Risk-free (annual): {rf_annual:.2%}  → weekly: {rf_w:.4%}  → daily: {daily_rf:.6%}\n")

    print("Returns (daily mean ± stdev) - Better Sample Size:")
    print(f"  • OracleZero: {fmt_pct(daily_mean_rp,2,True)}  ± {fmt_pct(daily_std_rp,2)}")
    print(f"  • SPY:        {fmt_pct(daily_mean_rb,2,True)}  ± {fmt_pct(daily_std_rb,2)}")
    print(f"  • Excess:     {fmt_pct(daily_mean_ex,2,True)}  ± {fmt_pct(daily_std_ex,2)}")
    print()
    
    print("Returns (weekly mean ± stdev) - Aggregated:")
    print(f"  • OracleZero: {fmt_pct(mean_rp,2,True)}  ± {fmt_pct(std_rp,2)}")
    print(f"  • SPY:        {fmt_pct(mean_rb,2,True)}  ± {fmt_pct(std_rb,2)}")
    print(f"  • Excess:     {fmt_pct(mean_ex,2,True)}  ± {fmt_pct(std_ex,2)}")
    print()

    print("Cumulative since start:")
    print(f"  • OracleZero: {fmt_pct(cum_rp,2,True)}")
    print(f"  • SPY:        {fmt_pct(cum_rb,2,True)}")
    print(f"  • Outperformance: {fmt_pct(cum_ex,2,True)}")
    print()

    print("Risk metrics:")
    print(f"  • Max drawdown (OZ):  {fmt_pct(mdd_rp,2)}")
    print(f"  • Max drawdown (SPY): {fmt_pct(mdd_rb,2)}")
    print(f"  • Sharpe (annualized, OZ): {fmt_num(sharpe_ann,3,True)}")
    print(f"  • Information Ratio (annualized): {fmt_num(ir_ann,3,True)}")
    print()
    
    print("Daily Risk Metrics (Better Sample Size):")
    daily_mdd_rp = max_drawdown(daily_rp)
    daily_mdd_rb = max_drawdown(daily_rb)
    print(f"  • Max drawdown (OZ):  {fmt_pct(daily_mdd_rp,2)}")
    print(f"  • Max drawdown (SPY): {fmt_pct(daily_mdd_rb,2)}")
    print(f"  • Sharpe (annualized, OZ): {fmt_num(daily_sharpe_ann,3,True)}")
    print(f"  • Information Ratio (annualized): {fmt_num(daily_ir_ann,3,True)}")
    print()

    # Daily significance tests (better sample size)
    daily_t_stat, daily_df, daily_p_val = ttest_two_sided_mean_gt_zero(daily_excess)
    (daily_ci_lo, daily_ci_hi), daily_prob_pos = bootstrap_mean_ci(daily_excess, iters=boots, seed=42)
    
    print("Significance vs SPY (daily excess) - Better Sample Size:")
    print(f"  • Paired t-test: t = {fmt_num(daily_t_stat,3,True)}  (df={daily_df}),  p = {fmt_num(daily_p_val,4)}")
    print(f"  • Bootstrap 95% CI for mean excess: [{fmt_pct(daily_ci_lo,2)}, {fmt_pct(daily_ci_hi,2)}]")
    print(f"  • Bootstrap Pr(mean excess > 0): {daily_prob_pos:.2%}")
    print()
    
    print("Significance vs SPY (weekly excess) - Aggregated:")
    print(f"  • Paired t-test: t = {fmt_num(t_stat,3,True)}  (df={df}),  p = {fmt_num(p_val,4)}")
    print(f"  • Bootstrap 95% CI for mean excess: [{fmt_pct(ci_lo,2)}, {fmt_pct(ci_hi,2)}]")
    print(f"  • Bootstrap Pr(mean excess > 0): {prob_pos:.2%}")
    print()

    simple_cum_return = fetch_simple_cumulative(engine, str(start), str(end))

    print("Validation Check:")
    print(f"  • Simple return (start → end): {fmt_pct(simple_cum_return,2,True)}")
    print(f"  • Report cumulative (weekly compounding): {fmt_pct(cum_rp,2,True)}")
    diff = simple_cum_return - cum_rp
    print(f"  • Difference: {fmt_pct(diff,2,True)}")
    print()

    # Last few days for sanity (better granularity)
    k_daily = min(10, n_daily)
    tail_daily_rp = daily_rp[-k_daily:]
    tail_daily_rb = daily_rb[-k_daily:]
    print(f"Last {k_daily} days (OZ vs SPY):")
    for i in range(k_daily):
        date_idx = len(daily_dates) - k_daily + i
        if date_idx >= 0 and date_idx < len(daily_dates):
            print(f"  {daily_dates[date_idx]}  |  OZ {fmt_pct(tail_daily_rp[i],2,True)}   SPY {fmt_pct(tail_daily_rb[i],2,True)}   Δ {fmt_pct(tail_daily_rp[i]-tail_daily_rb[i],2,True)}")
    print()
    
    # Last few weeks for sanity
    k = min(6, n)
    tail_rp = rp[-k:]
    tail_rb = rb[-k:]
    print(f"Last {k} weeks (OZ vs SPY) - Aggregated:")
    for i in range(k):
        print(f"  {dates[-k+i]}  |  OZ {fmt_pct(tail_rp[i],2,True)}   SPY {fmt_pct(tail_rb[i],2,True)}   Δ {fmt_pct(tail_rp[i]-tail_rb[i],2,True)}")

    print("\n==============================================================\n")
    return 0

# --------------------------- Main ----------------------------
if __name__ == "__main__":
    # Run with default parameters
    code = run_report(since=None, weeks=None, rf_annual=0.00, boots=10000)
    raise SystemExit(code)
