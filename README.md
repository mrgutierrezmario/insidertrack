# InsiderTrack

Track stock trades made by U.S. Congress members, corporate insiders, and institutional investors ("whales") — then get composite signal scores and alerts based on their moves.

---

## What it does

- **Congressional trades** — every House and Senate disclosure required by the STOCK Act
- **Corporate Form 4 insiders** — SEC filings from executives and directors
- **Institutional whales** — SEC 13F quarterly holdings (Buffett, Soros, Bridgewater, Ackman, Renaissance)
- **Federal Reserve officials** — OGE financial disclosure trades
- **Composite signal scores** — 0–100 score per ticker combining smart money, insider activity, momentum, and sentiment
- **Alerts** — rule-based notifications when signals, whale moves, or earnings thresholds are hit
- **Investment simulator** — what $X would be worth if you'd bought on any insider's disclosure date, vs. SPY
- **Signal outcomes** — tracks whether signal scores predicted price direction at 30, 60, and 90 days
- **Watchlist** — follow tickers, get personalized earnings calendar, receive email reports
- **Markets overview** — live macro indicators, top movers, Fed funds rate
- **News sentiment** — aggregated headlines with sentiment scoring per ticker
- **Earnings calendar** — upcoming reports for tracked and watchlisted tickers

---

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Docker Desktop | any recent | https://www.docker.com/products/docker-desktop |
| Python | 3.11+ | https://www.python.org |
| Node.js | 18+ | https://nodejs.org |

---

## Quick Start

```bash
cd stock-tracker
bash start.sh
```

The script will:
1. Start PostgreSQL in Docker (or use a local install if available)
2. Install Python packages
3. Install Node packages (first run only)
4. Build the frontend
5. Start the backend on port 8003 (which also serves the built frontend)

Press **Ctrl+C** to shut everything down cleanly.

| Service | URL |
|---|---|
| App | http://localhost:8003 |
| API docs | http://localhost:8003/docs |
| Database | localhost:5433 (Docker) or 5432 (local) |

---

## Production (Docker + Tailscale Funnel)

`start.sh` above is the development loop. The always-on deployment is a
self-contained Docker stack in `deploy/` — the same shape as the
lecture-note-app: Postgres 18 + a Tailscale sidecar that publishes the app on a
fixed HTTPS URL via Funnel, with the app sharing the sidecar's network
namespace.

```bash
deploy/start.sh    # build/update + start everything (safe to re-run)
deploy/stop.sh     # stop; data is kept in Docker volumes
docker compose -f deploy/compose.yml logs -f app
```

- Config lives in `deploy/.env` (git-ignored; created from `deploy/.env.example`
  with generated secrets on first run). Set `TS_HOSTNAME` and `PUBLIC_DOMAIN`
  to `<TS_HOSTNAME>.<your tailnet>.ts.net`.
- First run: the stack asks for a one-time Tailscale sign-in (or set
  `TS_AUTHKEY`). If the database is empty and `deploy/state/` contains a
  `*.dump` (pg_dump custom format), the newest one is restored automatically.
- Local access without Funnel: `http://localhost:${APP_PORT}` (default 8013).
- The nightly `pg_dump` (04:00 UTC, last 7 kept) lands in the `backups` volume:
  `docker compose -f deploy/compose.yml exec app ls /backups`.
- If the Tailscale container restarts, the app notices within ~45 s that its
  network namespace is gone and restarts itself onto the new one.

## First Use

1. Open http://localhost:8003
2. Click **⟳ Sync** on the Dashboard — pulls ~20,000 congressional trade records (~30s)
3. Signals appear under **Active Signals** once the sync completes
4. Go to **⚙ Config** → set your watchlist email to receive reports and personalize the earnings calendar
5. Go to **Admin** (link in Config page) to configure optional API keys

---

## Configuring API Keys

Optional keys unlock additional features. Set them in the Admin panel (no restart needed) or in `app/ui_backend/.env`:

| Key | Feature | Where to get it |
|---|---|---|
| `ALPHA_VANTAGE_KEY` | Minute-by-minute intraday charts | alphavantage.co — free tier: 25 req/day |
| `ANTHROPIC_API_KEY` | AI bull/bear research summaries on ticker pages | console.anthropic.com — pay-as-you-go, cached 6h |
| `MAIL_USERNAME` + `MAIL_PASSWORD` | Email reports and alert notifications | Gmail address + App Password (myaccount.google.com/apppasswords) |

Keys set via the Admin UI are stored in the database and take effect immediately.

---

## Data Sources

### Congressional Trades
| Source | Update frequency | Lag |
|---|---|---|
| House Stock Watcher | Daily | Up to 45 days (STOCK Act deadline) |
| Senate Stock Watcher | Daily | Up to 45 days (STOCK Act deadline) |

### Corporate Insiders (Form 4)
| Source | Update frequency | Lag |
|---|---|---|
| SEC EDGAR | On demand (manual sync or daily job) | 2 business days |

### Institutional Whales (13F)
| Source | Update frequency | Lag |
|---|---|---|
| SEC EDGAR | Quarterly | 45–60 days after quarter end |

Pre-loaded funds: Berkshire Hathaway, Soros Fund Management, Renaissance Technologies, Bridgewater Associates, Pershing Square (Bill Ackman).

### Federal Reserve Officials
| Source | Update frequency | Lag |
|---|---|---|
| OGE financial disclosures | Daily sync | Varies by official |

---

## How Signals Work

Every ticker with a congressional trade in the last 45 days gets a **composite score (0–100)** built from five sub-scores:

| Component | Max points | What it measures |
|---|---|---|
| Smart money | 20 | Whale 13F activity for this ticker (new / increased / reduced / closed positions) |
| Congress | 25 | Congressional buys vs. sells (45-day window), weighted by the disclosed dollar bracket. Options count by contract direction (long call / short put = bullish); unknown contracts and bonds are neutral |
| Corporate insiders | 20 | SEC Form 4 open-market buys vs. sells by officers, directors and 10% owners (90-day window), by dollar value. Buying counts more than selling; several insiders buying together earns a bonus |
| Momentum | 25 | SMA20/50 crossovers, RSI, price trend |
| Sentiment | 10 | News headline sentiment |
| Risk penalty | −20 | Stale disclosures (old trades or long disclosure lag) |

| Score range | Label |
|---|---|
| 70–100 | Strong Watch |
| 50–69 | Watch |
| 30–49 | Neutral |
| 15–29 | High Risk |
| 0–14 | Avoid for Now |

Signal outcomes are tracked at 30, 60, and 90 days — see the **Outcomes** page for historical hit rates.

---

## Daily Schedule

All times Eastern. Jobs run automatically when the backend is running.

| Time (ET) | Job |
|---|---|
| 6:30 AM | Sync corporate Form 4 insider filings |
| 6:45 AM | Pre-warm price history cache |
| 7:00 AM | Snapshot today's signal scores (for outcome tracking) |
| 7:15 AM | Sync Federal Reserve official disclosures |
| 7:30 AM | Fill 30/60/90-day outcomes for old snapshots |
| 8:00 AM | Sync congressional trades + morning analysis |
| 8:15 AM | Evaluate alert rules |
| 12:00 PM | Midday analysis |
| 12:15 PM | Evaluate alert rules |
| 6:00 PM | Evening analysis + email report |
| 6:15 PM | Evaluate alert rules |

Trigger any job manually from **API docs** at `/docs` or the relevant page in the app.

---

## Project Structure

```
stock-tracker/
├── start.sh                      ← Run this to start everything
├── deploy/                       ← Production stack: compose.yml, Dockerfile, start.sh
├── docker-compose.yml            ← Dev-only Postgres fallback for start.sh
├── logs/                         ← backend.log, frontend-build.log
│
├── app/ui_backend/
│   ├── .env                      ← Dev config (DB credentials, optional API keys)
│   ├── main.py                   ← FastAPI app + static frontend serving
│   ├── database.py               ← PostgreSQL connection (SQLAlchemy)
│   ├── config.py                 ← Pydantic settings from .env
│   │
│   ├── models/
│   │   ├── politician.py         ← Congress members
│   │   ├── trade.py              ← Congressional trade disclosures
│   │   ├── whale.py              ← 13F institutional holders + positions
│   │   ├── insider.py            ← Form 4 corporate insider transactions
│   │   ├── fed_official.py       ← Fed officials + trade disclosures
│   │   ├── alert.py              ← Alert rules + triggered events
│   │   ├── analysis.py           ← Morning/midday/evening analysis runs
│   │   ├── signal_outcome.py     ← 30/60/90-day signal outcome tracking
│   │   ├── subscriber.py         ← Email report subscribers
│   │   ├── watchlist.py          ← Per-user ticker watchlist
│   │   ├── app_setting.py        ← DB-stored API keys (Admin UI)
│   │   └── access.py             ← Site access log
│   │
│   ├── routers/
│   │   ├── trades.py             ← Congressional trade feed
│   │   ├── politicians.py        ← Manage tracked politicians
│   │   ├── whales.py             ← 13F whale holdings + feed
│   │   ├── insiders.py           ← Form 4 corporate insider transactions
│   │   ├── fed.py                ← Fed official disclosures
│   │   ├── signals.py            ← Composite signal scores
│   │   ├── analysis.py           ← Analysis run endpoints
│   │   ├── market.py             ← Price history, intraday, macro indicators
│   │   ├── news.py               ← News headlines + sentiment
│   │   ├── earnings.py           ← Earnings calendar
│   │   ├── simulator.py          ← $X investment projection + SPY comparison
│   │   ├── outcomes.py           ← Signal outcome tracking
│   │   ├── alerts.py             ← Alert rules + evaluation engine
│   │   ├── watchlist.py          ← Watchlist management
│   │   ├── filings.py            ← SEC filing viewer
│   │   ├── search.py             ← Global ticker search
│   │   ├── config.py             ← Subscriber + email report management
│   │   ├── app_settings.py       ← API key configuration (admin protected)
│   │   ├── access.py             ← Admin auth + rate limiting
│   │   └── ai.py                 ← AI research summary (Anthropic)
│   │
│   └── services/
│       ├── congress_fetcher.py   ← House + Senate trade sync
│       ├── edgar_fetcher.py      ← 13F XML whale holdings sync
│       ├── form4_fetcher.py      ← SEC Form 4 insider filing sync
│       ├── fed_fetcher.py        ← Fed official disclosure sync
│       ├── market_data.py        ← yfinance + Alpha Vantage price data
│       ├── news_fetcher.py       ← News headlines + sentiment scoring
│       ├── earnings_fetcher.py   ← Earnings calendar data
│       ├── analyzer.py           ← Analysis run logic
│       ├── alert_engine.py       ← Alert rule evaluation
│       ├── outcome_tracker.py    ← Signal snapshot + outcome fill
│       ├── email_sender.py       ← Gmail SMTP report delivery
│       ├── ai_summary.py         ← Anthropic API research summaries
│       └── scheduler.py          ← APScheduler cron jobs
│
└── app/ui_frontend/
    └── src/
        ├── pages/
        │   ├── Dashboard.jsx     ← Signals overview + performance chart
        │   ├── Feed.jsx          ← Congressional trade feed
        │   ├── Markets.jsx       ← Macro indicators + top movers
        │   ├── Signals.jsx       ← Composite signal scores
        │   ├── Activity.jsx      ← Unified timeline (Congress + insiders + Fed)
        │   ├── Politicians.jsx   ← Manage tracked politicians
        │   ├── Politician.jsx    ← Per-politician trade history
        │   ├── Whales.jsx        ← 13F whale holdings feed
        │   ├── Whale.jsx         ← Per-whale position detail
        │   ├── Insiders.jsx      ← Form 4 corporate insider transactions
        │   ├── Fed.jsx           ← Fed official disclosures
        │   ├── Ticker.jsx        ← Per-ticker: chart, congressional + insider trades
        │   ├── News.jsx          ← News feed with sentiment
        │   ├── Earnings.jsx      ← Earnings calendar
        │   ├── Simulator.jsx     ← Investment calculator + SPY benchmark
        │   ├── Outcomes.jsx      ← Signal outcome hit rates
        │   ├── Alerts.jsx        ← Alert rules + triggered events
        │   ├── Watchlist.jsx     ← Personal ticker watchlist
        │   ├── Filings.jsx       ← SEC filings viewer
        │   ├── Config.jsx        ← User settings (email, watchlist)
        │   ├── AdminConfig.jsx   ← Admin: API keys, subscribers, reports
        │   └── NotFound.jsx      ← 404 page
        ├── components/
        │   ├── TradeCard.jsx
        │   ├── StockChart.jsx
        │   ├── SignalBadge.jsx
        │   ├── WatchlistButton.jsx
        │   ├── SearchBar.jsx        ← Global search with ⌘K shortcut
        │   ├── AiSummaryPanel.jsx
        │   ├── ActivityChart.jsx    ← Activity feed timeline chart
        │   ├── ChartModal.jsx       ← Full-screen chart overlay
        │   ├── Disclaimer.jsx       ← First-visit legal disclaimer modal
        │   ├── SkeletonCard.jsx     ← Loading placeholder cards
        │   ├── ConfirmModal.jsx
        │   ├── ErrorBoundary.jsx
        │   └── LineChart.jsx
        └── lib/
            └── api.js            ← All backend API calls + admin token interceptor
```

---

## Security

- Admin password is validated server-side — never sent to the browser in plain text
- Admin token rotates hourly (HMAC-based, stateless)
- Login endpoint rate-limited to 10 attempts per 5 minutes per IP
- API keys (Alpha Vantage, Anthropic, Gmail) are stored encrypted in the database, never exposed in full
- Security headers on every response: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`

---

## Logs

```
logs/backend.log          ← FastAPI + scheduler output
logs/frontend-build.log   ← Vite build output
```

```bash
tail -f logs/backend.log
```

---

## Disclaimer

This tool uses legally required public disclosures. It is for informational and educational purposes only and does not constitute financial advice. Always do your own research before making investment decisions. Past insider trades are not a guarantee of future stock performance.
