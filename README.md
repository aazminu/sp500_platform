# S&P 500 Portfolio Management Platform

A comprehensive platform for managing and analyzing S&P 500 portfolios with automated rebalancing, real-time data integration, and advanced analytics. The platform combines market cap-weighted allocations with LLM-powered insights to optimize portfolio performance.

## Overview

This platform provides:
- **Automated Portfolio Rebalancing**: Market cap-weighted S&P 500 portfolio management
- **Real-time Data Integration**: Live market data, analyst estimates, and financial metrics
- **LLM-Powered Analysis**: AI-driven portfolio recommendations and insights
- **Performance Tracking**: Historical analysis and performance metrics
- **Modern Web Interface**: React-based dashboard for portfolio monitoring

## Architecture

- **Backend**: Flask API with PostgreSQL database
- **Frontend**: React with Vite for fast development
- **Data Sources**: Financial Modeling Prep API, Alpaca Trading API
- **AI Integration**: Hugging Face transformers for LLM analysis
- **Trading**: Automated portfolio rebalancing via Alpaca

## Quick Start

### Prerequisites

- Python 3.9+
- PostgreSQL database
- Node.js 18+ (for frontend)
- API keys for:
  - Financial Modeling Prep
  - Alpaca Trading
  - Hugging Face (optional, for LLM features)
  - Resend (optional, for email notifications)

### 1. Environment Setup

Create and activate a virtual environment:

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. Install Dependencies

```bash
# Backend dependencies
pip install -r requirements.txt

# Frontend dependencies
cd frontend
npm install
cd ..
```

### 3. Database Setup

Create a PostgreSQL database and set up the schema:

```bash
cd ingestion
python -c "
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))

with open('schema.sql', 'r') as f:
    schema = f.read()
    
with engine.connect() as conn:
    conn.execute(text(schema))
    conn.commit()
"
```

### 4. Environment Configuration

Create a `.env` file in the root directory:

```env
# Database
DATABASE_URL=postgresql://username:password@localhost:5432/database_name

# API Keys
FMP_API_KEY=your_fmp_api_key
ALPACA_KEY=your_alpaca_key
ALPACA_SECRET=your_alpaca_secret
HF_TOKEN=your_huggingface_token

# Optional: Email notifications
RESEND_KEY=your_resend_key

# Trading Configuration
DRY_RUN=1
MIN_TRADE_NOTIONAL=5
POST_SLEEP_SECS=0.35

# Frontend
FRONTEND_ORIGIN=http://localhost:5173
```

### 5. Initial Data Population

Run the data ingestion scripts to populate your database:

```bash
cd ingestion

# Fetch S&P 500 tickers and basic data
python fetch_tickers.py
python fetch_prices.py
python fetch_metrics.py
python fetch_profiles.py

# Fetch analyst data
python fetch_analyst_estimates.py
python fetch_analyst_labels.py

# Fetch news and historical data
python fetch_stock_news.py
python fetch_historical_market_cap.py
python fetch_historical_analyst.py

# Generate LLM analysis (optional)
python fetch_weekly_llm.py
```

### 6. Start the Application

```bash
# Start backend (in one terminal)
cd backend
python app.py

# Start frontend (in another terminal)
cd frontend
npm run dev
```

The application will be available at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:5000

## Project Structure

```
sp500_platform/
├── backend/                 # Flask API server
│   └── app.py              # Main API endpoints
├── frontend/               # React application
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── pages/         # Page components
│   │   └── api.js         # API client
│   └── package.json
├── ingestion/              # Data ingestion scripts
│   ├── fetch_*.py         # Data fetching scripts
│   ├── run_trades.py      # Portfolio rebalancing
│   ├── run_all.py         # Orchestration script
│   └── util scripts/      # Utility scripts
├── prompting-training/     # ML model training
├── csvs/                   # Data exports
└── requirements.txt        # Python dependencies
```

## Core Features

### Portfolio Management
- **Automated Rebalancing**: Market cap-weighted S&P 500 portfolio rebalancing
- **Cash Management**: Conservative cash handling with safety buffers
- **Trade Execution**: Two-phase execution (sells first, then buys)
- **Position Tracking**: Real-time position monitoring and valuation

### Data Integration
- **Market Data**: Real-time prices, volumes, and market metrics
- **Analyst Data**: Earnings estimates, ratings, and price targets
- **Financial Metrics**: Key ratios, valuations, and performance indicators
- **News Integration**: Stock-specific news and sentiment analysis

### Analytics
- **Performance Analysis**: Historical performance tracking and analysis
- **Allocation Comparison**: FMP vs LLM allocation recommendations
- **Risk Metrics**: Portfolio risk assessment and monitoring
- **Visualization**: Interactive charts and data visualization

### Automation
- **Scheduled Updates**: Automated data ingestion and analysis
- **Email Reports**: Weekly performance summaries (optional)
- **Error Handling**: Robust error handling and recovery
- **Monitoring**: Execution tracking and performance logging

## API Endpoints

### Portfolio Management
- `GET /api/account` - Account information and balances
- `GET /api/positions` - Current portfolio positions
- `GET /api/history` - Portfolio performance history
- `GET /api/history/orders` - Order history
- `GET /api/history/activities` - Account activities

### Analysis
- `GET /portfolio-analysis` - Portfolio analysis dashboard data
- `GET /api/stocks` - Available stocks list
- `GET /api/stocks/{ticker}/info` - Stock information
- `GET /api/stocks/{ticker}/prompt` - LLM prompt data

### Trading (Backend Only)
- Portfolio rebalancing via `run_trades.py`
- Automated execution with safety checks
- Dry-run mode for testing

## Configuration

### Trading Parameters
- `DRY_RUN`: Set to 1 for testing, 0 for live trading
- `MIN_TRADE_NOTIONAL`: Minimum trade size in dollars
- `POST_SLEEP_SECS`: Delay between API calls

### Data Sources
- **Financial Modeling Prep**: Stock data, analyst estimates, financial metrics
- **Alpaca**: Trading execution and account management
- **Hugging Face**: LLM inference for analysis (optional)

## Development

### Running Tests
```bash
# Backend tests (if available)
python -m pytest tests/

# Frontend linting
cd frontend
npm run lint
```

### Data Management
```bash
# Reset database
cd ingestion/util\ scripts
python reset.py

# Export data
python export.py

# Validate data integrity
python validate_data.py
```

### Deployment
```bash
# Build frontend
cd frontend
npm run build

# Deploy backend
cd backend
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```
