#!/usr/bin/env python3
"""
Script to check the data used for P-Value calculation and re-calculate it.
This helps diagnose why P-Values might be high by examining the underlying data.
"""

import os
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from scipy import stats
import numpy as np

# Load environment variables
load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables")
    exit(1)

def get_historical_data(timeframe='ytd'):
    """
    Fetches historical portfolio equity and benchmark data from the database.
    """
    end_date = datetime.now().date()
    if timeframe == 'ytd':
        start_date = datetime(end_date.year, 1, 1).date()
    elif timeframe == '3m':
        start_date = end_date - timedelta(days=90)
    elif timeframe == '1m':
        start_date = end_date - timedelta(days=30)
    elif timeframe == '1w':
        start_date = end_date - timedelta(days=7)
    else:
        print(f"⚠️ Warning: Unknown timeframe '{timeframe}'. Defaulting to YTD.")
        start_date = datetime(end_date.year, 1, 1).date()

    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Fetch portfolio NAV data
                cur.execute(
                    """
                    SELECT week_start_date, equity
                    FROM nav_weekly
                    WHERE week_start_date >= %s AND week_start_date <= %s
                    ORDER BY week_start_date;
                    """,
                    (start_date, end_date)
                )
                nav_data = cur.fetchall()
                nav_df = pd.DataFrame(nav_data, columns=['date', 'equity'])
                nav_df['date'] = pd.to_datetime(nav_df['date'])
                nav_df = nav_df.set_index('date')
                nav_df = nav_df.sort_index()

                # Fetch benchmark data (SPY)
                cur.execute(
                    """
                    SELECT px_date, adj_close
                    FROM benchmark_weekly
                    WHERE symbol = 'SPY' AND px_date >= %s AND px_date <= %s
                    ORDER BY px_date;
                    """,
                    (start_date, end_date)
                )
                benchmark_data = cur.fetchall()
                benchmark_df = pd.DataFrame(benchmark_data, columns=['date', 'adj_close'])
                benchmark_df['date'] = pd.to_datetime(benchmark_df['date'])
                benchmark_df = benchmark_df.set_index('date')
                benchmark_df = benchmark_df.sort_index()

        return nav_df, benchmark_df

    except Exception as e:
        print(f"❌ Error fetching historical data: {e}")
        return pd.DataFrame(), pd.DataFrame()

def calculate_p_value(excess_returns):
    """
    Calculates the p-value for excess returns using a one-sample t-test.
    Null hypothesis: mean excess return is zero.
    """
    if len(excess_returns) < 2: # Need at least 2 data points for t-test
        return np.nan, np.nan, 0

    # Convert to numpy array and ensure numeric type
    excess_returns = np.array(excess_returns, dtype=float)
    
    # Remove any NaN values
    excess_returns = excess_returns[~np.isnan(excess_returns)]
    
    if len(excess_returns) < 2:
        return np.nan, np.nan, 0

    # Perform one-sample t-test against a mean of zero
    # We are testing if the mean of excess returns is significantly different from zero.
    t_stat, p_value = stats.ttest_1samp(excess_returns, 0)
    return t_stat, p_value, len(excess_returns)

def check_p_value_data():
    """
    Main function to fetch data, calculate returns, and check p-values.
    """
    print("🔍 Checking P-Value data and calculations...")
    print("=" * 80)

    timeframes = ['1w', '1m', '3m', 'ytd']

    for tf in timeframes:
        print(f"\n📊 Analyzing {tf} timeframe:")
        nav_df, benchmark_df = get_historical_data(tf)

        if nav_df.empty or benchmark_df.empty:
            print(f"   No sufficient data found for {tf} timeframe.")
            continue

        # Merge dataframes on date
        merged_df = pd.merge(nav_df, benchmark_df, left_index=True, right_index=True, how='inner')

        if merged_df.empty:
            print(f"   No common dates found between portfolio and benchmark for {tf}.")
            continue

        # Convert to float to avoid Decimal issues
        merged_df['equity'] = merged_df['equity'].astype(float)
        merged_df['adj_close'] = merged_df['adj_close'].astype(float)
        
        # Calculate daily returns
        merged_df['portfolio_return'] = merged_df['equity'].pct_change()
        merged_df['benchmark_return'] = merged_df['adj_close'].pct_change()

        # Drop the first row which will have NaN returns
        merged_df = merged_df.dropna(subset=['portfolio_return', 'benchmark_return'])

        if merged_df.empty:
            print(f"   Not enough data points to calculate returns for {tf}.")
            continue

        # Calculate excess returns
        merged_df['excess_return'] = merged_df['portfolio_return'] - merged_df['benchmark_return']

        # Debug: Show sample data
        print(f"   Sample portfolio returns: {merged_df['portfolio_return'].head(3).tolist()}")
        print(f"   Sample benchmark returns: {merged_df['benchmark_return'].head(3).tolist()}")
        print(f"   Sample excess returns: {merged_df['excess_return'].head(3).tolist()}")

        # Calculate P-Value
        t_stat, p_value, num_data_points = calculate_p_value(merged_df['excess_return'])

        print(f"   Data points for calculation: {num_data_points}")
        if num_data_points > 1:
            print(f"   Mean daily excess return: {merged_df['excess_return'].mean():.6f}")
            print(f"   Std dev daily excess return: {merged_df['excess_return'].std():.6f}")
            print(f"   Min excess return: {merged_df['excess_return'].min():.6f}")
            print(f"   Max excess return: {merged_df['excess_return'].max():.6f}")
            print(f"   Calculated T-statistic: {t_stat:.4f}")
            print(f"   Calculated P-Value: {p_value:.4f}")
            if p_value < 0.05:
                print("   ✅ P-Value is statistically significant (p < 0.05)")
            else:
                print("   ❌ P-Value is NOT statistically significant (p >= 0.05)")
        else:
            print("   Insufficient data points to calculate P-Value.")

if __name__ == "__main__":
    check_p_value_data()
