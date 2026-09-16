# Investment Movement Tracker App — Claude AI Project Brief

## Goal

Build an app that tracks stock market movements, institutional activity, insider activity, and market signals to help support investment decisions.

The app should not be designed as a guaranteed trading system or “copy this person and get rich” tool. It should be a decision-support platform that helps identify stocks worth researching based on multiple signals.

## Core Concept

The app should track and summarize:

1. Live or near-live stock price movements
2. Institutional investor activity
3. Insider buying and selling
4. SEC filings
5. ETF and fund activity
6. Momentum and technical signals
7. News and sentiment
8. Earnings and major market events

The purpose is to help answer:

> “Is this stock worth researching right now?”

Not:

> “Should I blindly buy this stock today?”

## Important Reality Check

Truly live stock trade data from exchanges like Nasdaq and NYSE is usually not fully free. Most free APIs are limited in one or more ways:

- 15-minute delayed data
- request limits
- limited symbols
- limited WebSocket access
- free only for prototypes
- restricted redistribution rights

If this app becomes public or commercial, exchange licensing rules may matter.

## Best Free or Freemium APIs to Consider

## 1. Finnhub

Best starting point for the MVP.

### Useful Features

- Real-time stock quotes
- WebSocket support
- Insider transactions
- Earnings data
- Market news
- News sentiment
- Economic calendar
- Technical indicators

### Best Use

Use Finnhub for:

- real-time or near-real-time quote data
- news sentiment
- insider transactions
- earnings calendar
- alerts

### Example WebSocket Concept

```javascript
const socket = new WebSocket('wss://ws.finnhub.io?token=YOUR_API_KEY');

socket.onopen = function () {
  socket.send(JSON.stringify({
    type: 'subscribe',
    symbol: 'AAPL'
  }));
};

socket.onmessage = function (event) {
  const data = JSON.parse(event.data);
  console.log(data);
};
```

## 2. Alpha Vantage

Good for prototypes and smaller projects.

### Useful Features

- Historical stock prices
- Technical indicators
- Fundamental data
- Simple REST API

### Downsides

- Strict rate limits
- Not ideal for high-frequency real-time streaming
- Better for analysis than live trading dashboards

## 3. Polygon.io

One of the strongest market data APIs.

### Useful Features

- Real-time and historical stock data
- WebSockets
- Options data
- Crypto data
- Fast API responses

### Downsides

- Free tier is limited
- Paid tiers can become expensive
- Better suited once the app grows beyond the MVP

## 4. Marketstack

Simple and easy to integrate.

### Useful Features

- REST-based market data
- Global stock data
- Historical prices

### Downsides

- Free tier is limited
- Real-time data may require a paid plan

## 5. Financial Modeling Prep

Very useful for this type of investment decision app because it provides more than just price data.

### Useful Features

- Stock prices
- Financial statements
- Ratios
- SEC filings
- Insider trading
- Earnings
- Company profiles
- Analyst estimates
- Market news

### Best Use

Use Financial Modeling Prep for:

- fundamentals
- valuation metrics
- company financials
- SEC filing summaries
- insider activity
- earnings data

## 6. Alpaca Markets

Useful if the app may eventually support paper trading or live trade execution.

### Useful Features

- Paper trading
- Trading API
- Market data API
- WebSockets
- Developer-friendly platform

### Best Use

Use Alpaca for:

- paper trading simulations
- eventual trade execution
- portfolio testing
- strategy backtesting workflows

## Free Public Data Sources

## SEC EDGAR

Use SEC EDGAR for official filings.

### Important Filings to Track

- 13F filings: institutional holdings
- Form 4: insider transactions
- Schedule 13D: activist or large ownership stakes
- Schedule 13G: passive large ownership stakes
- 10-K: annual reports
- 10-Q: quarterly reports
- 8-K: major company events

### 13F Limitation

13F data is delayed. Large institutional investors usually report quarterly, and filings can be submitted up to 45 days after quarter-end. This means it should be used for idea generation, not real-time trade copying.

## Recommended MVP

Start with a focused MVP instead of trying to build a full trading terminal.

## MVP Features

1. User stock watchlist
2. Investor watchlist
3. SEC filing tracker
4. Insider transaction tracker
5. Price momentum scanner
6. Earnings calendar
7. News sentiment feed
8. Smart money movement feed
9. Basic signal score
10. Alerts

## Recommended Investors to Track

The app can track public filings or public activity from major investors and funds.

### Long-Term Investors

- Warren Buffett / Berkshire Hathaway
- Bill Ackman / Pershing Square
- Ray Dalio / Bridgewater Associates
- Stanley Druckenmiller
- Michael Burry / Scion Asset Management

### More Frequent Public Trade Visibility

- ARK Invest / Cathie Wood
- Some ETF managers that publish daily holdings
- Insider transactions through Form 4 filings

## Key App Screens

## 1. Dashboard

Show:

- top smart money activity
- unusual insider buying
- top momentum stocks
- stocks with new filings
- stocks with major news
- upcoming earnings
- high signal score stocks

## 2. Stock Detail Page

For each stock, show:

- price chart
- volume
- moving averages
- RSI or momentum indicators
- recent filings
- insider transactions
- institutional ownership changes
- news sentiment
- earnings date
- risk score
- AI-generated summary

## 3. Investor Detail Page

For each tracked investor or fund, show:

- latest holdings
- new buys
- sells
- increased positions
- reduced positions
- sector exposure
- top holdings
- historical portfolio changes

## 4. Alerts Page

Allow users to create alerts such as:

- insider buys over a certain dollar amount
- multiple insiders buying the same stock
- major fund opens a new position
- stock breaks above moving average
- unusual volume spike
- earnings within 7 days
- high signal score triggered

## Suggested Scoring Model

Create a combined investment signal score.

```text
Investment Signal Score =
Smart Money Score
+ Insider Activity Score
+ Momentum Score
+ Fundamentals Score
+ Sentiment Score
- Risk Score
```

## Example Output

```text
Ticker: NVDA

Smart Money Score: 82 / 100
Insider Activity Score: 55 / 100
Momentum Score: 91 / 100
Fundamentals Score: 76 / 100
Sentiment Score: 80 / 100
Risk Score: 68 / 100

Final Signal Score: 78 / 100

Interpretation:
Strong momentum and institutional interest, but risk is elevated due to valuation and volatility.
```

## Signal Categories

Use plain-language labels:

- Strong Watch
- Watch
- Neutral
- High Risk
- Avoid for Now

Avoid labels like:

- Guaranteed Buy
- Easy Money
- 100% Winner
- Must Buy Now

## Technical Architecture

## Recommended Stack

### Frontend

- React
- Vite
- Tailwind CSS
- Recharts or TradingView widget for charts

### Backend

- Python FastAPI

### Database

- PostgreSQL

### Background Jobs

Use one of:

- APScheduler
- Celery
- Redis Queue
- Airflow, if the data pipeline becomes complex

### Storage

Use one of:

- local storage for MVP
- MinIO for local S3-compatible storage
- AWS S3 for production

## Recommended Data Flow

Do not call financial APIs directly from the frontend.

Use this architecture:

```text
External APIs
    ↓
Background Worker / Scheduler
    ↓
Backend Processing Layer
    ↓
PostgreSQL Database
    ↓
FastAPI Backend
    ↓
React Frontend
```

Avoid this:

```text
React Frontend
    ↓
External Stock API
```

Reasons:

- exposes API keys
- causes rate-limit problems
- makes caching harder
- weakens security
- slows the frontend
- makes future scaling harder

## Database Tables

Possible starting schema:

```text
users
watchlists
stocks
stock_prices
investors
investor_holdings
sec_filings
insider_transactions
news_articles
signal_scores
alerts
api_ingestion_logs
```

## Example Tables

## stocks

```text
id
ticker
company_name
sector
industry
exchange
market_cap
created_at
updated_at
```

## stock_prices

```text
id
stock_id
timestamp
open
high
low
close
volume
source
created_at
```

## insider_transactions

```text
id
stock_id
insider_name
insider_title
transaction_type
shares
price
transaction_value
transaction_date
filing_date
source_url
created_at
```

## investor_holdings

```text
id
investor_id
stock_id
shares
market_value
portfolio_weight
change_type
reporting_period
filing_date
source_url
created_at
```

## signal_scores

```text
id
stock_id
smart_money_score
insider_score
momentum_score
fundamentals_score
sentiment_score
risk_score
final_score
summary
created_at
```

## Backend API Endpoints

Possible FastAPI endpoints:

```text
GET /api/stocks
GET /api/stocks/{ticker}
GET /api/stocks/{ticker}/prices
GET /api/stocks/{ticker}/signals
GET /api/stocks/{ticker}/filings
GET /api/stocks/{ticker}/insiders
GET /api/investors
GET /api/investors/{id}
GET /api/investors/{id}/holdings
GET /api/dashboard
POST /api/watchlist
DELETE /api/watchlist/{ticker}
POST /api/alerts
GET /api/alerts
```

## AI Features

Add AI summaries after the raw data works.

Possible AI-generated summaries:

1. Stock movement summary
2. Filing summary
3. Insider buying explanation
4. Risk warning
5. Bull case / bear case
6. “Why this stock is appearing today”

Example:

```text
AAPL appeared on today’s watchlist because it had above-average volume,
positive news sentiment, and increased institutional exposure in the latest
filings. However, there were no recent insider purchases, and valuation remains
above its sector average.
```

## Risk Management Rules

The app should always include risk notes.

Important rules:

- Never tell users a trade is guaranteed.
- Never imply that copying a billionaire guarantees profits.
- Always explain reporting delays.
- Always show data source and timestamp.
- Always separate facts from interpretation.
- Always warn when data is delayed.
- Avoid acting like a licensed financial advisor.

## Good User-Facing Language

Use language like:

```text
This stock may be worth researching.
```

```text
This signal is based on delayed public filings and recent price momentum.
```

```text
Institutional activity is one input, not a complete investment thesis.
```

```text
Risk is elevated because volatility and valuation are both high.
```

## Bad User-Facing Language

Avoid language like:

```text
Buy this now.
```

```text
This will make you money.
```

```text
Warren Buffett bought it, so you should too.
```

```text
Guaranteed winner.
```

## Development Roadmap

## Phase 1: MVP Data Pipeline

- Connect to one stock price API
- Connect to SEC EDGAR
- Store stock symbols
- Store price data
- Store filings
- Store insider transactions
- Build basic backend endpoints

## Phase 2: Dashboard

- Build React dashboard
- Add watchlist
- Add stock detail page
- Add filing feed
- Add insider transaction feed
- Add basic charts

## Phase 3: Signal Scoring

- Add smart money score
- Add insider activity score
- Add momentum score
- Add risk score
- Combine into final signal score

## Phase 4: Alerts

- Email alerts
- Push notifications
- High-value insider buy alert
- New 13F position alert
- Momentum breakout alert

## Phase 5: AI Layer

- AI-generated summaries
- AI risk explanations
- Bull/bear thesis generator
- Plain-English filing summaries

## Phase 6: Paper Trading

- Integrate Alpaca paper trading
- Track hypothetical performance
- Compare signal scores against future returns
- Improve scoring model based on outcomes

## Best Starting Build

The strongest MVP is:

```text
13F tracking
+ Form 4 insider buying
+ stock price momentum
+ earnings calendar
+ news sentiment
+ AI summary score
```

This is realistic, useful, and technically achievable.

## Final Product Positioning

The app should be positioned as:

> A smart money and market movement research assistant for investors.

Not:

> A guaranteed stock-picking machine.

## Claude AI Task Request

Please help design and build this app as a full-stack project.

Use:

- React + Vite + Tailwind for the frontend
- Python FastAPI for the backend
- PostgreSQL for the database
- background workers for API ingestion
- SEC EDGAR plus one or more market data APIs
- clean, modular, production-ready code
- secure API key handling
- clear documentation
- Docker Compose for local development

Start by creating:

1. A project folder structure
2. Docker Compose setup
3. Backend FastAPI skeleton
4. PostgreSQL schema
5. React dashboard skeleton
6. Example API ingestion worker
7. README with setup instructions

The app should prioritize data reliability, risk awareness, and decision support rather than blind trade copying.
