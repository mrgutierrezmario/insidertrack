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
- The app's own nightly `pg_dump` (04:00 ET, last 7 kept) lands in the `backups`
  volume: `docker compose -f deploy/compose.yml exec app ls /backups`. That
  copy dies with the Docker host, so there is also a **host-side, off-site
  backup**:

  ```bash
  deploy/backup-setup.sh   # once, on the Mac: rclone + encrypted Google Drive folder + nightly launchd job
  deploy/backup.sh         # any time: DB dump + .env + Tailscale identity → deploy/state/backups, synced off-site
  deploy/restore.sh --from-remote latest   # new machine: pull the off-site copy and rebuild the stack (same URL)
  ```

  Backups are encrypted before they leave the machine (rclone crypt); the
  passphrase is printed once by the setup script — keep it in a password
  manager. The Google Drive connection can be shared with lecture-note-app
  (same `gdrive` rclone remote, separate encrypted folder). Failures email
  `MAIL_ADMIN_TO`.
- If the Tailscale container restarts, the app notices within ~45 s that its
  network namespace is gone and restarts itself onto the new one.

## First Use

1. Open http://localhost:8003
2. Sign in to **Admin** (gear icon → Admin) and click **⟳ Sync** on the Dashboard — pulls the last ~90 days of House and Senate filings straight from the Clerk and the EFD (a few minutes; one PDF per filing)
3. Optionally **Admin → Data sources → Backfill history** to import older filings (a full year takes tens of minutes; safe to re-run)
4. Signals appear once the sync completes — every member with a filed disclosure is tracked by default; mute anyone on the Politicians page to keep them out of signals and alerts
5. **Settings** → set your watchlist email to receive reports and personalize the earnings calendar
6. **Admin** → optional API keys (AI provider, Alpha Vantage, mail)

---

## Configuring API Keys

Optional keys unlock additional features. Set them in the Admin panel (no restart needed) or in `app/ui_backend/.env`:

| Key | Feature | Where to get it |
|---|---|---|
| `ALPHA_VANTAGE_KEY` | Minute-by-minute intraday charts, news sentiment | alphavantage.co — free tier: 25 req/day |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` | AI bull/bear research notes on ticker pages. `AI_PROVIDER` picks the writer (claude / gemini / openai); other configured providers are fallbacks. Visitors can also bring their own key in Settings | console.anthropic.com / aistudio.google.com / platform.openai.com — cached 6h per ticker |
| `MAIL_USERNAME` + `MAIL_PASSWORD` | Email reports, alert notifications, data-source notices | Gmail address + App Password (myaccount.google.com/apppasswords) |
| `MAIL_ADMIN_TO` | Where operational notices go (a scraper failing or gone quiet). Defaults to the sender | — |

Keys set via the Admin UI are stored in the database and take effect immediately.

---

## Data Sources

### Congressional Trades
| Source | Update frequency | Lag |
|---|---|---|
| House Clerk — Periodic Transaction Report PDFs (disclosures-clerk.house.gov) | Daily, rolling 90-day window | Up to 45 days (STOCK Act deadline) |
| Senate EFD — electronic PTRs (efdsearch.senate.gov) | Daily, rolling 90-day window | Up to 45 days (STOCK Act deadline) |

Only electronically-filed reports are parsed (scanned paper filings have no text layer). Each row records the owner (member / spouse / dependent child / joint), the asset kind (stock / option / other), the disclosed dollar bracket, and a **direction** — the trade's bet on the ticker. Options follow their contract (long call / short put = bullish); an option whose filing doesn't say call or put, and bonds, are neutral and don't count toward the signal. Party and state come from the `unitedstates/congress-legislators` roster.

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
Roster only (seeded at startup, refreshable from the page). Board members have been barred from holding individual stocks since 2022, and OGE publishes disclosures as PDFs with no API, so the Fed page shows who is on the Board with an empty (compliant) trade list.

### Freshness monitoring
Every sync records its outcome per source. `GET /health` reports each source as `ok` / `stale` (runs succeed but no new rows for longer than expected — usually a site change the parser misses silently) / `failing` (three consecutive failures). **Admin → Data sources** shows the same, and a daily 9 AM ET job emails `MAIL_ADMIN_TO` only when something is stale or failing.

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
| 4:00 AM | Nightly `pg_dump` (last 7 kept) |
| 5:30 AM | Refresh trade staleness buckets (`risk_level`) |
| 6:00 AM Sat | Sync 13F whale holdings (idempotent; only does work after each quarterly deadline) |
| 6:30 AM | Sync corporate Form 4 insider filings |
| 6:45 AM | Pre-warm price history cache |
| 7:00 AM | Snapshot today's signal scores (for outcome tracking) |
| 7:30 AM | Fill 30/60/90-day outcomes for old snapshots |
| 8:00 AM | Sync congressional trades + morning analysis + email report |
| 8:15 AM | Evaluate alert rules |
| 9:00 AM | Data-source health check → admin email if anything is stale/failing |
| 12:00 PM | Midday analysis + email report |
| 12:15 PM | Evaluate alert rules |
| 6:00 PM | Evening analysis + email report |
| 6:15 PM | Evaluate alert rules |
| hourly | Sweep expired market-cache rows |

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
│   │   ├── politician.py         ← Congress members (tracked by default; untrack = mute)
│   │   ├── trade.py              ← Congressional trade disclosures (+ owner, asset_type, direction, amount bounds)
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
│   │   └── ai.py                 ← AI research notes (site or visitor key)
│   │
│   └── services/
│       ├── congress_fetcher.py   ← House Clerk + Senate EFD sync, historical backfill
│       ├── trade_semantics.py    ← owner / asset type / direction / amount parsing (one place)
│       ├── source_health.py      ← per-source freshness (ok / stale / failing)
│       ├── providers.py          ← Claude / Gemini / OpenAI clients for research notes
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
│       ├── ai_summary.py         ← AI research notes (provider fallback, 6h cache)
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
        │   ├── AiProviderPanel.tsx  ← Admin: AI provider, keys, live model lists
        │   ├── OwnAiSettings.tsx    ← Settings: bring-your-own AI key
        │   ├── DataSourcesPanel.tsx ← Admin: scraper freshness + history backfill
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
- API keys (Alpha Vantage, AI providers, Gmail) are stored in the database and never exposed in full; a visitor's own AI key is used for that request only and never stored or logged
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
