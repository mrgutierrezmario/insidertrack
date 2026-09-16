# Checkpoint — 2026-09-16 (deployment rebuilt on Tailscale Funnel)

> Supersedes the 2026-05-18 checkpoint (kept below for history).

## State of the Project

Live at **https://mgnts-stock-tracker.tail3659a6.ts.net** (Tailscale Funnel,
Let's Encrypt cert, fixed URL) as its own Docker stack — the same shape as
lecture-note-app. The old ngrok URL (`blast-morally-echo.ngrok-free.dev`) is
gone for good.

## What happened

The app had been running as bare `uvicorn` + `ngrok` processes inside the dev
container (`start.sh`) against the dev container's local Postgres 18. When the
dev container restarted (2026-09-15) the processes died with it, taking the
public URL down. Data was intact in the local Postgres data directory.

Also: the project had **never been a git repository** — no `.git`, nothing on
GitHub. Fixed today (see below).

## What's running (Docker Desktop on the Mac, driven from the dev container)

| Service | Where | Notes |
|---|---|---|
| `stock-tracker-app` | Docker (`deploy/compose.yml`) | FastAPI + built React UI on :8003 → Mac :8013 |
| `stock-tracker-postgres` | Docker, named volume | 18-alpine; restored from `deploy/state/stocktracker-snapshot-2026-09-16.dump` (20 tables, 924 trades) |
| `stock-tracker-tailscale` | Docker, named volume | Funnel → app; node `mgnts-stock-tracker`, signed in with GitHub (tailnet `mrgutierrezmario.github`) |

```bash
deploy/start.sh    # build/update + start (safe to re-run)
deploy/stop.sh
docker compose -f deploy/compose.yml logs -f app
```

Config: `deploy/.env` (git-ignored) — `DB_PASSWORD`, `TS_HOSTNAME`,
`PUBLIC_DOMAIN`, `APP_PORT`, `ADMIN_PASSWORD`, `ALPHA_VANTAGE_KEY`, mail
credentials. The app runs with `COOKIE_SECURE=true` and
`TRUSTED_PROXIES=127.0.0.1` (Funnel proxies from inside the shared namespace and
passes the real client IP in `X-Forwarded-For`).

## Lessons / gotchas baked into the scripts

- **Tailscale first sign-in**: `containerboot` gives `tailscale up` 60 s, then
  exits and restarts — rotating the login link every minute *and* orphaning the
  app's shared network namespace. `deploy/start.sh` therefore stops the tunnel
  and runs a one-shot `tailscale up` against the same state volume; that link
  stays valid until used. Only happens once (state persists).
- **Shared network namespace is fragile**: any restart of the tailscale
  container leaves the app unable to resolve `postgres`. `docker-entrypoint.sh`
  has a watchdog: 45 s without DNS → SIGTERM, 10 s grace, SIGKILL, exit 1 →
  Docker restarts the app onto the new namespace (verified: ~55 s to recover).
  lecture-note-app has the same exposure and no watchdog yet.
- **Dev-container shell exports `POSTGRES_USER/PASSWORD/DB`** (dev/devdb), and
  shell variables beat `.env` in compose interpolation. The compose file now
  hardcodes `stockuser`/`stocktracker` and reads the password as
  `DB_PASSWORD`, so nothing in the environment can point the app at the wrong DB.
- **Docker credential helper**: the dev container's `~/.docker/config.json`
  points at a VS Code credsStore that isn't available in a plain shell, so
  image pulls fail with `error getting credentials`. Workaround when building
  from a plain shell: `DOCKER_CONFIG=<dir with an empty {} config.json>`.
- **Host port 8003 belongs to the dev container**, so the stack publishes 8013.

## Removed

`start-docker.sh` (ngrok runbook), the `ngrok` service in the root
`docker-compose.yml` (now dev-DB-only), the ngrok step in `start.sh`, ngrok
permission entries in `.claude/settings.local.json`.

## Git / GitHub

Initialised as a git repository on 2026-09-16 and pushed to
`github.com/mrgutierrezmario/stock-tracker` (private). Secrets and local state
are ignored: `.env`, `deploy/.env`, `deploy/state/`, `backups/`, `logs/`,
`db_migration.dump`.

## Still open

- Off-site backups (lecture-note-app has `deploy/backup.sh` + rclone; this
  stack only keeps the nightly dump in a Docker volume).
- Add the same network watchdog to lecture-note-app.
- Decide whether to make the GitHub repo public (scrub personal details first,
  as was done for lecture-note-app).

---

# InsiderTrack — Checkpoint (2026-05-18)

## What's been built

### Backend (FastAPI, port 8003)
- Congressional trade sync + analysis (morning / midday / evening periods)
- Politician profiles with trade history and AI summaries
- Corporate Form 4 insider transactions (`/insiders`)
- 13F whale holdings sync from EDGAR XML (`/whales`, `/whale/:id`)
- Fed Reserve official trade disclosures (`/fed`)
- Composite signal scoring with reasons (`/signals`)
- Earnings calendar with watchlist enrichment
- News sentiment aggregation
- Portfolio simulator with SPY benchmark
- Outcomes tracking (signal → price result)
- Alert rules engine with 6 trigger types + email notify
- Watchlist (ticker + email stored per user)
- Markets overview (top movers, indices, Fed rate)
- SEC filings viewer
- Global ticker search (`/search`)
- Email report delivery (morning/midday/evening)
- APScheduler cron jobs (Fed sync, analysis, alerts, outcomes)

### Security (completed)
- [x] `SecurityHeadersMiddleware` — X-Frame-Options, X-Content-Type-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy
- [x] CORS locked to `localhost:5173/5174/5175` (no wildcard)
- [x] Admin password removed from frontend bundle entirely
- [x] `/access/admin/verify` — validates password server-side, returns rotating HMAC token
- [x] Hourly rotating HMAC token (stateless, no DB) — `sha256(password:hour)[:32]`
- [x] In-memory rate limiter on admin verify — 10 attempts / 5-minute window → 429
- [x] `require_admin` FastAPI Depends() on all sensitive endpoints
- [x] `/settings/keys` (GET, PATCH, DELETE) — require admin token
- [x] `/config/subscribers` (GET, POST) — require admin token
- [x] `/config/subscribers/lookup?email=` — unauthenticated self-service, returns own record only
- [x] Axios interceptor auto-attaches `X-Admin-Token` from sessionStorage to every request

### UX fixes (completed)
- [x] Signals page: `computed_at` timestamp + refresh button + ticker search + label filter pills
- [x] Dashboard: "Last analysis" date + "synced {time}" feedback after sync
- [x] Insiders: "Last loaded" timestamp
- [x] Whales: "Last loaded" timestamp, switched raw fetch() → api.js `getWhaleFeed()`
- [x] Feed: collapsible filter bar, sort by trade date / disclosure date
- [x] Simulator: SPY benchmark overlay on growth chart with +/- comparison caption
- [x] Politicians: name search filter
- [x] Earnings: enriched with watchlist tickers via localStorage email
- [x] Config (user): self-service subscription lookup, no admin required
- [x] AdminConfig: `confirm()` dialogs replaced with `ConfirmModal` component
- [x] Config (user): `confirm()` dialogs replaced with `ConfirmModal`
- [x] SearchBar: `Cmd+K` / `Ctrl+K` keyboard shortcut, `⌘K` hint in input
- [x] `ErrorBoundary` wrapping all routes — shows "Reload page" on crash
- [x] Feed filter bar: auto-opens on desktop (`window.innerWidth >= 768`), collapsed on mobile

### Bug fixes (completed 2026-05-18)
- [x] `ai_summary.py`: `technical_signals(db)` iterated dict keys instead of `.get("signals", [])` — AI context always had `signal: null`
- [x] `Insiders.jsx`: auto-sync called admin-protected `syncInsiders()` unconditionally on first empty load; now gated on `sessionStorage.getItem(ADMIN_TOKEN_KEY)`
- [x] `Insiders.jsx`: empty-state message now shows correct guidance based on auth status
- [x] `api.js`: removed dead `getActivityFeed` export (unused alias for `getFedTrades`)
- [x] `politicians.py` `get_politician_trades`: returned raw ORM objects missing `risk_level` — risk badge was invisible on politician detail pages
- [x] `email_sender.py`: `mail_from` defaulted to `""`, producing a broken `From: InsiderTrack <>` header; now falls back to `mail_username` in both `send_report` and `send_simple_email`
- [x] `market.py` `macro_indicators()`: yfinance 0.2.40 changed batch `yf.download()` MultiIndex to ticker-first, breaking `data["Close"]` silently; switched to per-symbol `yf.Ticker(sym).history()` calls
- [x] `outcomes.py` `list_outcomes()`: rows lacked politician context; added batch subquery to find most recent tracked-politician trade per ticker
- [x] `Outcomes.jsx`: added Politician column with `/politician/:id` link; politician field added to CSV export
- [x] `Activity.jsx`: removed stale `useRef` import (unused after pagination rework)

### Features completed (2026-05-18)
- [x] Activity feed: "After date" filter — passed server-side to all three sources (congressional `since`, insiders `after`, fed `after`)
- [x] Filings institutions: moved from hardcoded dict to `filing_institutions` DB table; auto-seeded on first startup; admin CRUD (add/delete) in AdminConfig; `POST /filings/institutions`, `DELETE /filings/institutions/{cik}`
- [x] CSV export on all major pages: Feed, Insiders, Signals, Activity, Outcomes, Fed, Whales

---

## Remaining gaps

_All previously tracked gaps are now closed. Items below are aspirational / nice-to-have._

### 🟡 Minor polish

#### Outcomes: politician lookup uses most-recent trade per ticker
- The batch subquery joins on `max(trade_date)` per ticker. If two politicians traded the same ticker on the same date, only one is returned (non-deterministic). A full resolution would require a `politician_id` FK on `SignalOutcome`, but that requires a schema migration and is low priority.

#### Activity feed: "Load more" with date filter
- When `afterDate` is set and the user clicks "Load more", the offset advances but the date is already filtered server-side, so results are correct. However, if there are fewer than `PAGE_SIZE` results per source after the date cutoff, `has_more` may show spuriously. Minor UX issue.

---

## Key file map

| Area | File |
|------|------|
| Security headers + CORS | `backend/main.py` |
| Admin auth + rate limit | `backend/routers/access.py` |
| API key management | `backend/routers/app_settings.py` |
| Subscriber management | `backend/routers/config.py` |
| Signal scoring | `backend/routers/signals.py` |
| Simulator + SPY | `backend/routers/simulator.py` |
| Trade feed sort | `backend/routers/trades.py` |
| Earnings + watchlist | `backend/routers/earnings.py` |
| Filings institutions (DB) | `backend/routers/filings.py`, `backend/models/filing_institution.py` |
| Admin token (frontend) | `frontend/src/pages/AdminConfig.jsx` |
| Axios interceptor | `frontend/src/lib/api.js` |
| Confirm modal | `frontend/src/components/ConfirmModal.jsx` |
| Error boundary | `frontend/src/components/ErrorBoundary.jsx` |
