-- ============================================================================
-- SP500 PLATFORM DATABASE SCHEMA
-- ============================================================================
-- This schema defines the database structure for the S&P 500 analysis platform
-- Each table stores different types of financial data with varying update frequencies

-- UPSERT LOGIC IS USED AS:
-- 50% fewer database calls = faster execution
-- No race conditions = more reliable
-- Database can optimize the entire operation
-- Less network overhead = better performance
-- VS CHECK-THEN-UPSERT:
-- Two separate database calls (check if exists, then insert/update)

-- Clean up existing tables (if any)
DROP TABLE IF EXISTS allocations CASCADE;
DROP TABLE IF EXISTS analyst_estimates CASCADE;
DROP TABLE IF EXISTS analyst_labels CASCADE;
DROP TABLE IF EXISTS grades_historical CASCADE;
DROP TABLE IF EXISTS key_metrics CASCADE;
DROP TABLE IF EXISTS prices CASCADE;
DROP TABLE IF EXISTS profiles CASCADE;
DROP TABLE IF EXISTS stock_news CASCADE;
DROP TABLE IF EXISTS tickers CASCADE;
DROP TABLE IF EXISTS predictions CASCADE;
DROP TABLE IF EXISTS ingestion_metadata CASCADE;
DROP TABLE IF EXISTS weekly_stats CASCADE;

-- ============================================================================
-- CORE DATA TABLES
-- ============================================================================

-- Tickers table: Master list of S&P 500 companies
-- Updated: Quarterly (when S&P 500 composition changes)
-- Purpose: Reference table for all other data, contains company metadata
CREATE TABLE IF NOT EXISTS tickers (
    ticker VARCHAR(10) PRIMARY KEY,
    company_name TEXT NOT NULL,
    sector TEXT,
    date_added DATE
);

-- Prices table: Daily OHLCV price data for each ticker
-- Updated: Daily (market data)
-- Purpose: Historical price analysis, volatility calculations, performance tracking
CREATE TABLE IF NOT EXISTS prices (
    ticker VARCHAR(10),
    price_date DATE,
    open_price NUMERIC(12,4),
    high_price NUMERIC(12,4),
    low_price NUMERIC(12,4),
    close_price NUMERIC(12,4),
    volume BIGINT,
    PRIMARY KEY (ticker, price_date),
    FOREIGN KEY (ticker) REFERENCES tickers(ticker) ON DELETE CASCADE
);

-- Index for fast price lookups
CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices (ticker, price_date);

-- ============================================================================
-- ANALYST & RATING DATA
-- ============================================================================

-- Analyst labels: Daily analyst ratings and scores
-- Updated: Daily (analyst updates)
-- Purpose: Sentiment analysis, buy/sell signals, fundamental scoring
CREATE TABLE IF NOT EXISTS analyst_labels (
    ticker VARCHAR(10) NOT NULL,
    label_date DATE NOT NULL,
    rating VARCHAR(3) NOT NULL,                    -- Letter grade (A-, B+, etc.)
    overall_score SMALLINT,                        -- 1-5 score
    discounted_cash_flow_score SMALLINT,           -- 1-5 score
    return_on_equity_score SMALLINT,               -- 1-5 score
    return_on_assets_score SMALLINT,               -- 1-5 score
    debt_to_equity_score SMALLINT,                 -- 1-5 score
    price_to_earnings_score SMALLINT,              -- 1-5 score
    price_to_book_score SMALLINT,                  -- 1-5 score
    source TEXT,
    PRIMARY KEY (ticker, label_date)
);

-- Analyst estimates: Quarterly earnings/revenue forecasts
-- Updated: Quarterly (earnings seasons)
-- Purpose: Forward-looking analysis, earnings expectations, growth projections
CREATE TABLE IF NOT EXISTS analyst_estimates (
    symbol VARCHAR(10) NOT NULL,
    report_date DATE NOT NULL,
    revenue_low BIGINT,
    revenue_high BIGINT,
    revenue_avg BIGINT,
    ebitda_low BIGINT,
    ebitda_high BIGINT,
    ebitda_avg BIGINT,
    ebit_low BIGINT,
    ebit_high BIGINT,
    ebit_avg BIGINT,
    net_income_low BIGINT,
    net_income_high BIGINT,
    net_income_avg BIGINT,
    sga_expense_low BIGINT,
    sga_expense_high BIGINT,
    sga_expense_avg BIGINT,
    eps_avg NUMERIC(10,4),
    eps_high NUMERIC(10,4),
    eps_low NUMERIC(10,4),
    num_analysts_revenue INTEGER,
    num_analysts_eps INTEGER,
    source VARCHAR(50) NOT NULL,
    PRIMARY KEY (symbol, report_date)
);

-- Grades historical: Weekly analyst consensus ratings
-- Updated: Weekly (analyst consensus changes)
-- Purpose: Track analyst sentiment changes over time, consensus tracking
CREATE TABLE IF NOT EXISTS grades_historical (
    symbol VARCHAR(10) NOT NULL,
    rating_date DATE NOT NULL,
    analyst_ratings_buy INTEGER,
    analyst_ratings_hold INTEGER,
    analyst_ratings_sell INTEGER,
    analyst_ratings_strong_sell INTEGER,
    source VARCHAR(10) NOT NULL,
    PRIMARY KEY (symbol, rating_date)
);

-- ============================================================================
-- NEWS & SENTIMENT DATA
-- ============================================================================

-- Stock news: Daily news articles and sentiment data
-- Updated: Daily (news feeds)
-- Purpose: News sentiment analysis, event-driven trading signals
CREATE TABLE IF NOT EXISTS stock_news (
    url TEXT NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    published_date TIMESTAMP NOT NULL,
    publisher VARCHAR(255),
    title TEXT,
    image TEXT,
    site VARCHAR(255),
    text TEXT,
    source VARCHAR(10) NOT NULL,
    PRIMARY KEY (url)
);

-- ============================================================================
-- FUNDAMENTAL DATA
-- ============================================================================

-- Key metrics: Annual fundamental ratios and metrics
-- Updated: Annual (financial statements)
-- Purpose: Fundamental analysis, ratio comparisons, financial health assessment
CREATE TABLE IF NOT EXISTS key_metrics (
    ticker VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    metrics JSON NOT NULL,                         -- Flexible JSON storage for various ratios
    PRIMARY KEY (ticker, date),
    FOREIGN KEY (ticker) REFERENCES tickers(ticker) ON DELETE CASCADE
);

-- Profiles: Annual company profile and description data
-- Updated: Annual (company updates)
-- Purpose: Company descriptions, sector analysis, business model understanding
CREATE TABLE IF NOT EXISTS profiles (
    ticker VARCHAR(10) PRIMARY KEY,
    profile_data JSON NOT NULL,                    -- Company description, business model, etc.
    date_fetched DATE NOT NULL,
    FOREIGN KEY (ticker) REFERENCES tickers(ticker) ON DELETE CASCADE
);

-- ============================================================================
-- PORTFOLIO & ALLOCATION DATA
-- ============================================================================

-- Allocations: Weekly S&P 500 market cap-based allocations
-- Updated: Weekly (market cap changes)
-- Purpose: Benchmark portfolio weights, market cap tracking, index replication
CREATE TABLE IF NOT EXISTS allocations (
    ticker VARCHAR(10) NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
    allocation_date DATE NOT NULL,
    market_cap_usd BIGINT NOT NULL,                -- Raw market cap from FMP
    allocation_pct NUMERIC(7,6) NOT NULL,          -- Percentage weight (e.g., 0.061234 = 6.1234%)
    source VARCHAR(50) NOT NULL,                   -- Data source identifier
    retrieved_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, allocation_date)
);

-- Index for date-range queries
CREATE INDEX IF NOT EXISTS idx_allocations_date ON allocations (allocation_date);

-- ============================================================================
-- AI/LLM DATA
-- ============================================================================

-- Predictions: Weekly LLM-generated investment recommendations
-- Updated: Weekly (LLM analysis runs)
-- Purpose: AI-driven portfolio recommendations, allocation adjustments
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    request_data JSON NOT NULL,                    -- Input data sent to LLM
    response_data JSON NOT NULL,                   -- LLM response and recommendations
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Weekly LLM data: Structured LLM prompts and responses by ticker
-- Updated: Weekly (per-ticker LLM analysis)
-- Purpose: Track LLM recommendations over time, compare with actual performance
CREATE TABLE IF NOT EXISTS weekly_llm_data (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    week_start_date DATE NOT NULL,
    prompt_data JSONB NOT NULL,                    -- Full prompt sent to LLM
    response_data JSONB,                           -- LLM response (JSON format)
    status VARCHAR(20) DEFAULT 'pending',          -- pending, completed, failed
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    FOREIGN KEY (ticker) REFERENCES tickers(ticker) ON DELETE CASCADE
);

-- Indexes for LLM data performance
CREATE INDEX IF NOT EXISTS idx_weekly_llm_ticker_week ON weekly_llm_data (ticker, week_start_date);
CREATE INDEX IF NOT EXISTS idx_weekly_llm_status ON weekly_llm_data (status);

-- ============================================================================
-- WEEKLY STATS & REPORTING
-- ============================================================================

-- Weekly stats: Portfolio performance and script execution tracking
-- Updated: Weekly (when cron job runs)
-- Purpose: Email reporting, performance tracking, script monitoring
CREATE TABLE IF NOT EXISTS weekly_stats (
    id SERIAL PRIMARY KEY,
    week_start_date DATE NOT NULL,
    week_end_date DATE NOT NULL,
    portfolio_return_pct DECIMAL(8,4),              -- Weekly return percentage
    top_5_notional_changes JSONB,                   -- Top 5 position value changes
    scripts_executed JSONB,                         -- Script success/failure logs
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    email_sent BOOLEAN DEFAULT FALSE,
    email_sent_at TIMESTAMP
);

-- Index for weekly stats queries
CREATE INDEX IF NOT EXISTS idx_weekly_stats_week ON weekly_stats (week_start_date);

-- ============================================================================
-- METADATA & SCHEDULING
-- ============================================================================

-- Ingestion metadata: Tracks data update schedules and last run dates
-- Updated: Runtime (when scripts execute)
-- Purpose: Smart scheduling, data freshness tracking, S&P 500 composition monitoring
CREATE TABLE ingestion_metadata (
    table_name TEXT PRIMARY KEY,
    frequency TEXT NOT NULL,                       -- daily, weekly, quarterly, annual
    script_name TEXT,                              -- Python script that updates this table
    last_run_date DATE,                            -- Last successful data update
    smart_boundary BOOLEAN DEFAULT FALSE,          -- Use smart date boundaries
    boundary_days INTEGER DEFAULT 7,               -- Days to look back for updates
    sp500_tracked BOOLEAN DEFAULT FALSE,           -- Track S&P 500 composition changes
    last_sp500_check DATE                          -- Last S&P 500 composition check
);

-- ============================================================================
-- CONFIGURATION UPDATES
-- ============================================================================

-- Enable smart scheduling for quarterly/annual scripts
UPDATE ingestion_metadata 
SET smart_boundary = TRUE, boundary_days = 7 
WHERE frequency = 'quarterly';

UPDATE ingestion_metadata 
SET smart_boundary = TRUE, boundary_days = 14 
WHERE frequency = 'annual';

-- Enable S&P 500 tracking for data scripts
UPDATE ingestion_metadata 
SET sp500_tracked = TRUE 
WHERE script_name IN (
    'fetch_prices.py', 'fetch_historical_market_cap.py', 'fetch_metrics.py',
    'fetch_profile.py', 'fetch_analyst_labels.py', 'fetch_analyst_estimates.py',
    'fetch_historical_analyst.py', 'fetch_stock_news.py'
);
