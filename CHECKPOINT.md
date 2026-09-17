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

## Review findings — 2026-09-16 (code + datasets)

Fixed in commit "Review fixes":
- **Scheduler ran on UTC, not Eastern.** `BackgroundScheduler(timezone=ET)`
  does not apply to pre-built `CronTrigger` objects (they default to the
  process zone). Every report/alert/sync had been firing 4 h early: morning
  report at 4 AM ET, "evening" at 2 PM ET. All triggers now pass `timezone=ET`.
- **Duplicate congressional trades** (90 groups / 109 rows): `SessionLocal`
  has `autoflush=False`, so the exists-check inside a filing loop could not see
  rows added moments earlier. Added `db.flush()` after each insert (Senate and
  House); duplicates removed (kept lowest id).
- **Fed "trades" were fabricated placeholders**: three hard-coded rows
  attributed to Governors Waller and Bowman, source URL on a non-existent host
  (`efts.usethical.com`). Removed the seed and the rows. The OGE "API" the
  fetcher targets does not exist either (OGE publishes PDFs) — left in place
  with a comment; the Fed page shows the roster with no trades, which is the
  truthful state (board members cannot buy individual stocks since 2022).
- **13F whale data was stale** (Q1 2026) — the sync was admin-manual only and
  hadn't run since May. Added a weekly Saturday 06:00 ET `whale_sync` job
  (idempotent). Ran it: 655 Q2-2026 positions.
- **ARK had zero positions**: its CIK pointed at *ARK ETF Trust* (no 13Fs).
  Fixed to ARK Investment Management LLC (0001697748); 172 positions loaded.
- **Admin sessions died at the top of the hour**: token = sha256(pw:hour),
  so a login at 10:59 was invalid at 11:00. Verification now accepts the
  current and previous hour (matches the 1 h cookie).

Noted, not changed:
- 68 Form 4 duplicate groups are within a single accession (same insider,
  date, code, shares, price) — likely identical lots in the XML; spot-check
  before deduping.
- Form 4 rows with price 0 (1,496) are codes A/M/G/C (grants, exercises,
  gifts, conversions) — classified "other", not buys/sells. Correct.
- Pershing Square's Q2 2026 13F is not picked up (fetcher takes only the
  newest 13F-HR per CIK; Pershing may file an amendment first).
- Michael Burry / Scion: last 13F is 2025-Q3 — Scion deregistered, so this is
  expected; consider marking the holder inactive.
- `snapshot_gaps_14d` went 11 → 0 once the scheduler caught up.
- Pre-cleanup snapshot: `deploy/state/stocktracker-pre-cleanup-2026-09-16.dump`.

## UI pass — 2026-09-16 (look & feel)

Rendered every page at 1440 px and 390 px (Playwright, `scratchpad/shoot2.py`
against a `vite preview` proxied to the live API) and worked through the
review list in order:

1. **Terms gate** — removed the "10% of $100,000 service fee" clause; now a
   welcome + not-financial-advice notice + optional email signup, one
   Continue button.
2. **Navigation** — 16 flat links → app bar with 5 grouped menus (Signals ·
   Who's trading · Markets · My Watch · ⚙), hints per item, phone drawer.
3. **Mobile** — shared `.page-head` (title/subtitle/actions wrap), Politicians
   card no longer overflows, dense grids collapse, 16 px inputs (no iOS zoom).
4. **Brand / theme / PWA** — MG Network icons + logo mark, self-hosted Plus
   Jakarta Sans (CSP forbids Google Fonts), `site.webmanifest`, per-page
   `<title>`. **Light/dark**: all tokens are CSS variables in
   `src/index.css`; `lib/theme.ts` `C.*` now returns `var(--c-*)`, so the
   1,100 inline styles follow the theme with no per-page edits. Canvas charts
   read resolved colors via `resolvedPalette()` and rebuild on
   `insidertrack:theme`. Picker (System/Light/Dark) in Settings; no flash
   (inline script in index.html). 238 hard-coded hex values mapped to tokens.
5. **Admin controls hidden** for visitors (`hooks/useAdmin`, reactive on
   login/logout): Politicians add/edit/track/delete, Dashboard sync/run,
   Outcomes snapshot/fill, Alerts create/pause/delete/evaluate/mark-seen,
   Whales/Fed/Insiders sync, Politician detail track toggle. Nav badge only
   for admins ("unseen" is a global admin flag).
6. **Fed page** — reframed as a roster; copy explains the 2022 rules mean an
   empty trade list is the compliant state; fake OGE link removed; OGE fetch
   is a no-op (no such API). Roster: Kugler retired, Stephen Miran added,
   `ROSTER_AS_OF` + `FORMER_OFFICIALS` in `fed_fetcher.py`.
7. **Dashboard** — rebuilt around "what changed": stat strip (disclosed this
   week · top signal · latest read · alerts fired), latest analysis
   bullish/bearish, your watchlist, top-5 signals with score bars, latest
   disclosures, recent insiders; the 10-line chart moved to the bottom.
8. **Small gaps** — sub-score tooltips on Signals; the risk badge shows only
   for HIGH and reads "STALE" (it measures staleness); Whales header states
   "Data through 2026-Q2" with the 45-day lag note.

Tests: 70 frontend (vitest) + 149 backend pass.

## AI providers — 2026-09-17

Research notes now work like the lecture app's AI settings: `services/
providers.py` (Claude via the Anthropic SDK; Gemini and OpenAI via httpx),
`ai_provider` picks who writes the note, every other provider with a saved key
is a fallback, and the note records `provider/model` plus any fallback reason.
Keys/models are admin-editable in the Admin panel (`AiProviderPanel`) via the
existing `/settings/keys` store, with `GET /settings/ai` (public status),
`GET /settings/ai/gemini-models` (live list from Google) and
`POST /settings/ai/test?provider=`. Defaults: `claude-opus-5`,
`gemini-flash-latest`, `gpt-4o-mini`. Currently active: Gemini, using the same
key as the lecture app. Clearing a model field restores the config default.

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
