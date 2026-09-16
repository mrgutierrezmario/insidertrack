# InsiderTrack — Gap Audit (2026-05-19)

Full-codebase audit covering the FastAPI backend, React/Vite frontend, and
supporting services. Items are ordered by severity. Fixed items are noted with
✅ and a short description of the change made.

Severity legend: 🔴 High · 🟠 Medium · 🟡 Low

---

## 🟠 Security & authorization

### ✅ Subscriber PATCH/DELETE had no authorization
**`backend/routers/config.py`** — `PATCH /config/subscribers/{sub_id}` and
`DELETE /config/subscribers/{sub_id}` carried no auth and no ownership check.
Sequential integer IDs meant anyone could modify or delete any subscriber's
record by guessing an ID.

*Fix (2026-05-19):* Both endpoints now require either a valid admin token
(`X-Admin-Token` header, checked via `hmac.compare_digest`) or an `email`
query param that exactly matches the subscriber's stored email. The admin path
preserves the AdminConfig.jsx admin flow (token is auto-attached by the Axios
interceptor); the email-ownership path preserves the self-service Config.jsx
flow. `api.js` signatures updated to `updateSubscriber(id, body, email)` and
`deleteSubscriber(id, email)`, and all three call-sites in `Config.jsx` now
pass `mySub.email`.

---

### ✅ `add_subscriber` was unauthenticated and unthrottled
**`backend/routers/config.py`** — `POST /config/subscribers` (open self-signup)
had no rate limiting and could be abused to bulk-create subscriber rows.

*Fix (2026-05-19):* Added an in-memory rate limiter (`_check_sub_rate_limit`)
to `POST /config/subscribers`: max 5 signups per IP per 1-hour window, with
stale-key eviction. Returns 429 when the limit is exceeded.

---

### ✅ Non-constant-time secret comparison
**`backend/routers/access.py`** — `body.password != settings.admin_password`
(line 100) and `x_admin_token != _make_token(...)` (line 43) used plain `!=`,
which is not constant-time and is susceptible to a timing side-channel.

*Fix (2026-05-19):* Both comparisons replaced with `hmac.compare_digest`.
Added `import hmac`. The `_is_admin()` helper in `config.py` also uses
`hmac.compare_digest` for its inline token check.

---

### ✅ Admin token lives in `sessionStorage`
**`frontend/src/lib/api.js`** — the rotating HMAC admin token was stored in
`sessionStorage` and attached via an Axios interceptor. `sessionStorage` is
readable by any injected script (XSS).

*Fix (2026-05-19):* Migrated to httpOnly cookie auth. Added
`POST /access/admin/login` (sets `admin_token` httpOnly cookie, `samesite=lax`,
`max_age=3600`), `POST /access/admin/logout`, and `GET /access/admin/status`
to `access.py`. `require_admin` now reads the cookie first (then falls back to
the `X-Admin-Token` header for backward compat). `api.js` sets
`withCredentials: true` on the Axios instance and removed the token-injecting
interceptor. `AdminConfig.jsx` calls `adminLogin(pw)` on the login path and
`adminLogout()` on sign-out. `sessionStorage` now stores only the non-sensitive
UI flag `"1"` under `ADMIN_TOKEN_KEY` — no real secret is readable by JS.

---

### ✅ IP-based access gate is client-controlled
**`backend/routers/access.py`** — `_get_ip()` trusted `X-Forwarded-For`
unconditionally and used the *left-most* value, both of which are
client-controlled.

*Fix (2026-05-24):* Two-part change:
1. **`backend/routers/access.py`** — `_get_ip()` now checks
   `os.environ["TRUSTED_PROXIES"]` (comma-separated). It only consults
   `X-Forwarded-For` when the immediate peer (`request.client.host`) is in
   that list, and uses the *right-most* value (the address closest to the
   trusted proxy, which clients cannot forge). Without `TRUSTED_PROXIES` set,
   the header is ignored entirely.
2. **`start.sh`** — uvicorn is now launched with
   `--forwarded-allow-ips=""`. Uvicorn's built-in proxy-headers middleware
   defaulted to trusting `X-Forwarded-For` from `127.0.0.1`, which rewrote
   `request.client.host` *before* our code ran — defeating the
   `TRUSTED_PROXIES` check. Disabling the built-in middleware makes our
   `_get_ip()` the single source of truth.

The terms-agreement gate is still a soft gate by design, but spoofing it now
requires control of a trusted proxy IP, not just a header.

---

### ✅ Report emails leaked the subscriber list
**`backend/services/email_sender.py`** — `send_report()` set
`msg["To"] = ", ".join(recipients)`, so every subscriber saw every other
subscriber's email address in the `To:` header. Same issue in
`send_simple_email`.

*Fix (2026-05-19):* Both functions now loop over recipients, building and
sending a fresh `MIMEMultipart` per address inside a single SMTP connection.
Each recipient receives their own email with only their own address in `To:`.

---

## 🟠 Performance

### ✅ Composite signals are recomputed independently in 4 places
`technical_signals(db)` was invoked independently by `GET /signals/`,
`watchlist_with_signals`, `evaluate_alerts`, and `_gather_context`, each
triggering a full price-history fan-out.

*Fix (2026-05-19):* Added a module-level `_signals_cache` dict with a 5-minute
TTL to `signals.py`. All four callers share one computed result per window;
only the first call within a 5-minute period hits the price APIs. The cache
stores the plain JSON-serialisable result dict, so closed DB sessions are not
an issue for subsequent reads.

---

### ✅ N+1 query pattern in `technical_signals`
**`backend/routers/signals.py`** — the per-ticker loop ran
`_smart_money_score(ticker, db)`, `_risk_penalty(ticker, db)`, and a
latest-filing-date subquery individually for each ticker.

*Fix (2026-05-19):* `technical_signals` now calls `_compute_technical_signals`
which pre-fetches all data in 3 batch queries before the ticker loop:
1. All `WhalePosition` rows for active tickers (`.in_(tickers)`)
2. All recent `Trade` rows for risk penalty (`.in_(tickers)`)
3. `MAX(filing_date) GROUP BY ticker` for latest filing dates.
New helpers `_smart_money_from_positions` and `_risk_penalty_from_trades` operate
on the pre-fetched lists. The original per-ticker query functions are retained
for any callers that pass a single ticker.

---

### ✅ Foreign-key columns were not indexed
PostgreSQL does not auto-index FK columns. These were joined on constantly but
had no index:
- `trades.politician_id` (**`backend/models/trade.py`**)
- `whale_positions.holder_id` (**`backend/models/whale.py`**)
- `fed_trades.official_id` (**`backend/models/fed_official.py`**)

*Fix (2026-05-19):* Three `CREATE INDEX IF NOT EXISTS` statements added to
`_apply_migrations()` in **`backend/database.py`**. They run at startup and
are idempotent, so existing deployments pick them up automatically on next
restart:
```sql
CREATE INDEX IF NOT EXISTS ix_trades_politician_id ON trades (politician_id);
CREATE INDEX IF NOT EXISTS ix_whale_positions_holder_id ON whale_positions (holder_id);
CREATE INDEX IF NOT EXISTS ix_fed_trades_official_id ON fed_trades (official_id);
```

---

### ✅ In-memory caches grow unbounded
**`backend/services/market_data.py`** — `_cache` and `_history_cache` are plain
dicts. Entries are only TTL-checked on read; expired entries are never evicted,
so memory grows with the number of distinct tickers/intervals seen. The
`_attempts` defaultdict in `access.py` had the same issue.

*Fix (2026-05-19):* `_cache_set` and `_history_cache_set` now evict all expired
entries whenever the respective dict grows beyond 500 entries. The `_attempts`
dict in `access.py` was already fixed. Full LRU with `cachetools.TTLCache` would
be cleaner but this closes the unbounded-growth path at zero extra dependencies.

---

## 🟡 Data integrity & correctness

### ✅ Demo prices are served silently
**`backend/services/market_data.py`** — `get_current_price()` silently returned
demo values when yfinance failed. The Simulator, Signals, and Watchlist pages
displayed synthetic numbers with no indicator.

*Fix (2026-05-19):* `get_current_price(ticker, with_meta=True)` now returns
`{"price": float, "is_demo": bool}`. The Simulator (`/simulator/project`)
passes the flag through in its response. The Signals endpoint sets `is_demo`
on each ticker result by checking `history[-1].get("_demo")` from the price
history (which already carries the flag). Frontend pages can read these fields
to show a badge — rendering is left to the UI layer.

---

### ✅ Watchlist 7-day change is an approximation
**`backend/routers/watchlist.py`** — `watchlist_with_signals` computed the
"7-day" change from `hist[-8]["close"]`, which drifts by 1–2 days around
market holidays.

*Fix (2026-05-19):* Now computes `target = (today - 7 days).isoformat()` and
finds the most recent bar on or before that date using a reverse linear scan of
the history list. Falls back to the oldest available bar if the history is
shorter than 7 days. Accurate regardless of holiday schedule.

---

### ✅ Outcomes politician lookup is non-deterministic for legacy rows
**`backend/routers/outcomes.py`** — New rows store `politician_id` directly, but
legacy rows (NULL `politician_id`) fell back to a `max(trade_date)` subquery;
ties on the same date resolved arbitrarily.

*Fix (2026-05-19):* A `DISTINCT ON (t.ticker)` PostgreSQL backfill migration was
added to `_apply_migrations()` in `database.py`. It deterministically assigns the
most recent tracked-politician trade per ticker to any `signal_outcomes` row that
has a NULL `politician_id`. Runs at startup and is idempotent.

---

## 🟡 Reliability

### ✅ Scheduler had no misfire handling
**`backend/services/scheduler.py`** — `BackgroundScheduler` used the default
in-memory jobstore with no `misfire_grace_time`. If the process restarted, any
job that should have run during downtime was silently skipped.

*Fix (2026-05-19):* All 9 cron jobs now receive `misfire_grace_time=600`
(10 minutes). Jobs that were due within the past 10 minutes at startup will
still fire. Extracted into a single `mgtime` dict to keep the call sites
uniform.

---

### ✅ `get_ticker_info` has no fallback
**`backend/services/market_data.py`** — `get_ticker_info()` returned a bare
`{"ticker": ticker}` on yfinance failure, causing the UI to show blanks.

*Fix (2026-05-19):* Added a module-level `_ticker_info_cache` dict. Every
successful fetch is saved; on failure, the last known good result is returned
with `"_stale": True` so the UI can show a small indicator. Only falls back to
the bare dict when no prior result exists for the ticker.

---

## 🟡 UX gaps

### ✅ Admin-only action buttons appeared for all users
Sync buttons in **`Fed.jsx`**, **`Whales.jsx`**, and **`Dashboard.jsx`** were
visible to non-admin users but the underlying endpoints require admin.
Failures surfaced as a generic "Error — check backend logs." message.

*Fix (2026-05-19):* All three pages now import `ADMIN_TOKEN_KEY` from `api.js`
and gate their sync / analysis-run controls behind
`sessionStorage.getItem(ADMIN_TOKEN_KEY)`. Non-admin visitors no longer see
the buttons at all. This matches the pattern already used in `Insiders.jsx`.

---

### ✅ No automated tests (backend)
There was no test suite anywhere — no `pytest` for the backend, no component
tests for the frontend.

*Fix (2026-05-19):* Added `backend/tests/` with 79 passing tests across three
modules:
- **`test_signals.py`** — covers `_sma`, `_rsi`, `_momentum_score`,
  `_insider_score`, `_composite_label`, `_bullish_label`,
  `_smart_money_from_positions`, and `_risk_penalty_from_trades`
- **`test_pagination.py`** — covers `+1`-fetch `has_more` logic, risk-filter
  over-fetch slice, and `ge`/`le` query-param bound validation
- **`test_market_data.py`** — covers cache eviction, `_demo_history` output,
  and `get_current_price` `with_meta` flag

Run with `python3 -m pytest` from the `backend/` directory. Frontend component
tests remain open.

---

## Additional gaps — second audit pass (2026-05-19)

A deeper review of routers not covered in the first pass surfaced the
following. All code-level fixable items have been addressed.

### ✅ Watchlist DELETE had no ownership check
**`backend/routers/watchlist.py`** — `DELETE /watchlist/{item_id}` deleted by
raw integer ID with no auth and no ownership check, so anyone could delete any
user's watched ticker by guessing IDs — the same class of bug as the
subscriber PATCH/DELETE issue.

*Fix (2026-05-19):* `DELETE /watchlist/{item_id}` now requires an `email`
query param that is normalised (`_norm_email`) and must exactly match the
item's stored `email`; a missing or mismatched email returns 403. `api.js`
`removeFromWatchlist(id, email)` and `Watchlist.jsx`'s `remove()` now pass the
active email. (No admin override was added — the watchlist has no admin
management UI, unlike subscribers.)

*Fully closed (2026-05-25):* Replaced the email-as-auth-key pattern with a
per-user bearer token. New `WatchlistOwner` table (PK `email`, `token_hash`
= sha256 hex, `created_at`, `last_used_at`) — token itself is never stored.

Backend:
- `routers/watchlist.py` rewritten. `_require_owner(request, email, db)`
  reads `Authorization: Bearer <token>` (or `X-Watchlist-Token`), verifies
  `sha256(token) == owner.token_hash` via `hmac.compare_digest`, and bumps
  `last_used_at`. All four endpoints (`GET /`, `GET /signals`, `POST /`,
  `DELETE /{id}`) now require it. The 30/min/IP GET rate limiter is kept as
  defence-in-depth.
- `POST /watchlist/` mints a fresh token for a new email and returns it
  exactly once in `{"token": "..."}`. Migration-seeded legacy users (owner
  row with empty hash) get a token on their next POST without disruption.
- New `POST /watchlist/recover` rotates the token (replaces the hash) and
  emails the address the new value via the existing `send_simple_email`
  pipeline. Returns 200 whether the email exists or not to prevent
  enumeration. Rate-limited at 3/hr/IP.
- `database.py:_apply_migrations()` creates the table and seeds owner rows
  with empty hashes for every existing `watchlist_items.email` — those
  users will get a real token the next time they POST or via recovery.
- `DELETE /watchlist/{id}` now resolves the owner from the item's email
  (not the caller's claim) so a valid token + a guessed item id from
  another user still 403s.

Frontend:
- `lib/storage.ts` adds `WATCHLIST_TOKEN_KEY` (localStorage).
- `lib/api.ts` `watchlistAuthHeaders()` attaches the bearer header on every
  watchlist call. `addToWatchlist()` captures and stores the returned token
  on first add. `recoverWatchlistToken()` added.
- `pages/Watchlist.tsx` handles 401/403 by routing into a recovery UI:
  "email me a new token" button + paste-token input + "use a different
  email" escape hatch. `switchEmail` clears the stored token too.

Tests: `backend/tests/test_watchlist.py` — 24 new tests covering token
helpers, `_require_owner` (missing/wrong/seeded-empty/correct), first-add
mint, second-add-rejected-without-token, attacker-cannot-DELETE-by-id,
recovery rotates token + invalidates the old one + does not enumerate.

Frontend tests (48) and backend tests (103 total) all pass.

---

### ✅ `GET /ai/summary/{ticker}?refresh=true` is an unauthenticated paid call
**`backend/routers/ai.py`** — summaries are cached 6h, but `refresh=true`
bypasses the cache and forces a fresh Anthropic Claude API call, which costs
money. The endpoint had no auth and no rate limiting.

*Fix (2026-05-19):* `refresh=true` now requires a valid admin token (`X-Admin-Token`
header, checked via `hmac.compare_digest`). Non-admin callers receive 403. The
read path (no `refresh`) remains unauthenticated so the ticker page loads normally.

---

### ✅ `list_trades` over-fetches and reports an inaccurate `total`
**`backend/routers/trades.py`** — `list_trades` unconditionally set
`fetch_limit = (offset + limit) * 3`, computing `_risk_level()` in Python for
every row even when no risk filter was applied. `total` was `len(all_results)`,
the windowed count, not the real row count.

*Fix (2026-05-19):* When no `risk_level` filter is present, `list_trades` now
queries the exact page with `.offset().limit(limit + 1)` and a separate
`COUNT(*)` query — accurate total, no over-fetch. When `risk_level` is set,
the over-fetch path is retained (Python evaluation is unavoidable), with `total`
reporting the count within the fetched window.

---

### ✅ `macro_indicators` caches partial/empty results
**`backend/routers/market.py`** — `macro_indicators()` called `_cache_set` even
when the yfinance loop failed and `result` contained only `FED_RATE`, blanking
the macro panel for the full 5-minute TTL after a transient failure.

*Fix (2026-05-19):* The cache write is now guarded by `if len(result) > 1:` so
a yfinance failure that leaves only `FED_RATE` in the dict skips caching and
lets the next request retry immediately.

---

### ✅ `POST /alerts/run` blocks the request
**`backend/routers/alerts.py`** — `run_now` accepted a `BackgroundTasks`
parameter but ignored it, calling `evaluate_alerts(db)` synchronously.

*Fix (2026-05-19):* Changed to `background_tasks.add_task(evaluate_alerts, db)`;
the endpoint now returns `{"status": "started"}` immediately, consistent with
`/outcomes/snapshot`, `/outcomes/fill`, and `/fed/sync`.

---

### ✅ `GET /alerts/rules` is unauthenticated and exposes `notify_email`
**`backend/routers/alerts.py`** — `list_rules` returned each rule's
`notify_email` without any auth check.

*Fix (2026-05-19):* `list_rules` now accepts an optional `X-Admin-Token` header.
`notify_email` is included in the response only when the token is valid; non-admin
callers receive all other rule fields but the email field is omitted. Mutation
endpoints (create/patch/delete) were already admin-gated and continue to return
`notify_email` in their responses.

---

### ✅ No Content-Security-Policy; `X-XSS-Protection` is deprecated
**`backend/main.py`** — `SecurityHeadersMiddleware` set `X-XSS-Protection: 1;
mode=block` (deprecated, can introduce vulnerabilities in older browsers) and
had no `Content-Security-Policy`.

*Fix (2026-05-19):* `X-XSS-Protection` set to `"0"`. Added a `Content-Security-Policy`
header: `default-src 'self'` with `script-src`/`style-src` widened for the Vite
bundle (`'unsafe-inline'`, `'unsafe-eval'`), `img-src 'self' data: blob:`,
`connect-src 'self'`, and `font-src 'self' data:`. The `connect-src 'self'`
restriction is the key mitigation against XSS-driven exfiltration of the admin
token to external domains.

---

### ✅ Several list endpoints have no upper bound on `limit`
`GET /politicians/{id}/trades`, `GET /outcomes/`, `GET /alerts/events`, and
`GET /market/history/{ticker}` accepted unbounded or partially-bounded query
params.

*Fix (2026-05-19):* All four endpoints now use `Query(default=..., ge=1, le=500)`
(or `le=365` for `days`). `ge=1` prevents zero/negative values from passing
through to downstream calls. Required `Query` imports added to `politicians.py`
and `outcomes.py`.

---

## Additional gaps — third audit pass (2026-05-22)

### ✅ Snapshot stored demo prices, polluting win-rate stats
**`backend/services/outcome_tracker.py`** — `snapshot_signals` inserted a row
for every ticker with a `current_price`, regardless of whether the price was a
synthetic demo value from `market_data.py`'s yfinance fallback. The eventual
`return_30/60/90d` calculations would compare a real future close against a
fake baseline, silently corrupting the win-rate stats on the Outcomes page.

*Fix (2026-05-22):* `snapshot_signals` now checks `s.get("is_demo")` (set by
`technical_signals`) and skips those rows entirely. A summary log line records
the skipped count so operators can spot yfinance outages.

---

### ✅ No uniqueness guard on `(ticker, signal_date)`
**`backend/models/signal_outcome.py`** — duplicate prevention relied on a
`SELECT COUNT(*)` precheck inside `snapshot_signals`, which is racy if two
snapshot jobs ever overlap (manual `/outcomes/snapshot` trigger while the cron
fires, or two workers behind a load balancer).

*Fix (2026-05-22):* Added `CREATE UNIQUE INDEX IF NOT EXISTS
ux_signal_outcomes_ticker_date ON signal_outcomes (ticker, signal_date)` to
`_apply_migrations()`. `snapshot_signals` now uses
`postgresql.insert(...).on_conflict_do_nothing(index_elements=["ticker",
"signal_date"])` instead of `db.add` per row + a separate precheck. The insert
is now genuinely idempotent at the database level — re-running the job on the
same day is a no-op regardless of concurrency. `result.rowcount` reports the
real count of new rows.

---

### ✅ CORS allowed unused dev-server ports
**`backend/main.py`** — `allow_origins` listed `http://localhost:5173`,
`:5174`, and `:5175`, none of which are used now that the backend serves the
built frontend from `frontend/dist` on port 8003.

*Fix (2026-05-22):* Pared the list to `http://localhost:8003` and the public
ngrok domain (`https://blast-morally-echo.ngrok-free.dev`). Anything else is
rejected at the CORS layer.

---

### ✅ No HSTS header
**`backend/main.py`** — `SecurityHeadersMiddleware` covered CSP, frame
options, MIME sniffing, and referrer policy, but not `Strict-Transport-Security`.
Now that the app is exposed over HTTPS via ngrok, this should be set so browsers
remember to use HTTPS on subsequent visits.

*Fix (2026-05-22):* Added `Strict-Transport-Security:
max-age=31536000; includeSubDomains` (1 year, includes subdomains). `preload`
intentionally omitted — that requires owning a real domain and committing to
HTTPS forever.

---

### ✅ Pending outcome cells gave no indication of when they would fill
**`frontend/src/pages/Outcomes.jsx`** — `OutcomeChip` rendered the literal
string `pending` for any null outcome, with no hint of how long until the
fill job had enough lookback. Users were left to compute `signal_date +
30/60/90` in their head.

*Fix (2026-05-22):* `OutcomeChip` now accepts `signalDate` and `days` props
and computes the projected fill date (`signal_date + days`). The cell renders
`fills 2026-06-15` (or similar) instead of `pending`, with a tooltip
explaining the fill behaviour. Dates already in the past (where the row hasn't
filled despite being old enough — usually a yfinance outage) render in
amber as a heads-up.

---

## Additional gaps — fourth audit pass (2026-05-24)

### ✅ AI summary ticker input was unbounded
**`backend/routers/ai.py`** — `/ai/summary/{ticker}` accepted `ticker: str` of
any length and shape. The value flows into the Anthropic prompt and the
in-memory cache key, so an attacker could (a) blow up cache memory with
garbage keys and (b) on cache miss, trigger a paid Anthropic API call per
unique value.

*Fix (2026-05-24):* Validate before any cache lookup or external call. The
endpoint now matches `ticker` against `^[A-Z0-9.\-]{1,10}$` (tight enough to
catch garbage, loose enough for real tickers like `BRK.B` or `RY.TO`). Bad
input returns 400 before `_gather_context` or `generate_stock_summary` run.

---

### ✅ Email `From` header injection via admin-settable display name
**`backend/services/email_sender.py`** — `msg["From"] = f"{settings.mail_from_name} <{from_addr}>"`
used unsanitized concatenation. `mail_from_name` is editable in the admin UI
(`app_settings.py:52`), so a `\\r\\n` in the value would inject arbitrary
SMTP headers (`Bcc:`, `Cc:`, `Subject:`, …). Threat model is narrow (admin
attacking own users) but it's a classic SMTP header-injection class bug.

*Fix (2026-05-24):* Added `_safe_from(addr)` helper that strips CR/LF from
both name and address and builds the header via `email.utils.formataddr`,
which quotes the display name correctly. Both call sites in `send_report` and
`send_simple_email` use the helper.

---

### ✅ Anthropic client had no timeout
**`backend/services/ai_summary.py`** — `Anthropic(api_key=...)` used the SDK
default timeout of 10 minutes. A slow Anthropic response would tie up a
uvicorn worker for the full duration.

*Fix (2026-05-24):* Pass `timeout=30.0` when constructing the client. Long
enough for normal latency, short enough to free the worker if the upstream
hangs.

---

### ✅ AI summary read path had no per-IP rate limit
**`backend/routers/ai.py`** — even with ticker input validation, a tight loop
hitting valid tickers (`AAPL`, `MSFT`, ...) can force fresh Anthropic calls
whenever the cache misses. The endpoint is unauth on the read path by design,
so the only protection was the cache itself.

*Fix (2026-05-24):* Added `_check_ai_rate(request)` — per-IP deque-based
token bucket (mirrors the `/watchlist/` limiter). 20 summaries/min/IP, with
stale-bucket eviction at 500 entries. 21st hit returns 429. Runs *after*
input validation and *before* cache lookup, so abuse can't burn cache memory
either. Verified end-to-end: request 21 → 429, `/health` (different limiter
scope) unaffected.

---

### ✅ Backend logs grew unbounded; format was inconsistent
**`backend/main.py`** — `logging.basicConfig(level=logging.INFO)` configured a
single console handler with no rotation and the bare `%(message)s` format. The
file `logs/backend.log` (uvicorn's redirected stdout) grew indefinitely, and
log lines had no timestamp/level prefix for downstream parsing.

*Fix (2026-05-24):* Replaced `basicConfig` with explicit handler setup:
- **`RotatingFileHandler`** writing to `logs/backend-app.log`, 10 MB cap,
  5 backups (`backend-app.log.1` … `backend-app.log.5`). 60 MB max disk usage.
- **Console handler** retained so `logs/backend.log` (uvicorn redirect) still
  captures live output for `tail`-style inspection.
- Both handlers share `%(asctime)s %(levelname)s %(name)s: %(message)s` —
  consistent shape regardless of which sink you're reading. Idempotent guard
  means hot-reloads don't duplicate handlers.

Verified after restart: `logs/backend-app.log` exists with timestamped lines
like `2026-05-24 15:53:16,583 INFO services.scheduler: Scheduler started ...`.

---

### ✅ DB connection pool was untuned
**`backend/database.py`** — `create_engine(url)` used SQLAlchemy defaults
(`pool_size=5`, `max_overflow=10`, no `pool_pre_ping`). The scheduler holds
connections during multi-second jobs; with daily Form4/whale syncs running
while users browse, the pool can starve. Stale connections after a Postgres
restart aren't recycled — first query errors instead.

*Fix (2026-05-24):* `create_engine(..., pool_pre_ping=True, pool_size=10,
max_overflow=20, pool_recycle=3600)`. `pool_pre_ping` recycles dead
connections transparently; the larger pool handles the scheduler-plus-web
mix; `pool_recycle=3600` is a safety net for idle connections behind NAT.

---

## Additional gaps — fifth audit pass (2026-05-27)

### ✅ ADMIN_PASSWORD relied on the config default
**`backend/config.py`** — `admin_password: str = "191919"` was the fallback
when `.env` didn't set `ADMIN_PASSWORD`. The live backend's `.env` had no
entry, so every admin login was literally `191919`. Easy to miss because
the default is silent.

*Fix (2026-05-27):* Added `ADMIN_PASSWORD=191919` explicitly to `.env` with
a "change before any non-local deploy" comment, mirrored in `.env.example`.
No behaviour change (same password) but the value is now explicit in env
state and reviewable, and `.env.example` makes the requirement obvious for
anyone provisioning a fresh deploy.

---

### ✅ Admin-token cookie `secure=False` hardcoded
**`backend/routers/access.py:150`** — the httpOnly admin cookie was minted
with `secure=False`. Fine in plain-HTTP dev; in production behind ngrok
HTTPS it lets the cookie leak over any HTTP downgrade.

*Fix (2026-05-27):* New `cookie_secure: bool = False` in `Settings`,
sourced from `COOKIE_SECURE` env var. `access.py` now reads
`settings.cookie_secure`. `.env.example` documents flipping it to `true`
behind HTTPS. Verified: `COOKIE_SECURE=false` (dev) → `Set-Cookie`
returned without `Secure` attribute; flipping the env var would add it
without a code change.

---

### ✅ ngrok domain hardcoded in two places
**`backend/main.py:151`** (CORS allowlist) and **`start.sh:151`** (tunnel
target) both literal-named `blast-morally-echo.ngrok-free.dev`. A domain
rotation was a two-file code change.

*Fix (2026-05-27):* New `public_domain: str = ""` in `Settings`, sourced
from `PUBLIC_DOMAIN` env var. `main.py` builds the CORS allowlist
dynamically: localhost is always trusted, the public hostname is added
only if `PUBLIC_DOMAIN` is set. `start.sh` reads the same value (falls
back to grepping `.env` directly so it works before any python is loaded).
`docker-compose.yml`'s `ngrok` service uses `${PUBLIC_DOMAIN}` in its
command. One-line `.env` edit now rotates everywhere.

---

### ✅ No DB backup strategy
The Docker volume was the only copy of the production data. One
corruption = unrecoverable loss. No `pg_dump` script, no scheduled job.

*Fix (2026-05-27):* New `services/db_backup.py` with `run_backup()` (runs
`pg_dump` against `settings.database_url`, writes
`insidertrack-YYYY-MM-DD.dump` to `BACKUP_DIR`) and `prune_old(keep=7)`
(retains the last week of dailies). Scheduler runs `_db_backup_job` daily
at 04:00 ET via `CronTrigger(hour=4, minute=0)`. `backend/Dockerfile`
installs `postgresql-client` (supplies `pg_dump`). `docker-compose.yml`
adds `BACKUP_DIR=/backups` env and a `./backups:/backups` bind mount so
the dumps land on the host and survive container recreation.

Verified end-to-end against the running dev backend: manual `run_backup()`
produced a 96KB custom-format `.dump` in `logs/backups/`. Scheduler
startup log confirms `_db_backup_job` registered in the persistent
jobstore.

Restore command (one-off, manual):
```
pg_restore -U stockuser -d stocktracker --clean --if-exists \
    --no-owner --no-privileges  <  backups/insidertrack-YYYY-MM-DD.dump
```

---

### ✅ HTML injection in email templates
**`backend/services/email_sender.py`** and **`backend/services/alert_engine.py`** —
ticker symbols, insider names, alert messages, "reason" strings, and other
DB-sourced fields were interpolated raw into HTML email bodies via f-strings
(`{s['ticker']}`, `{e["message"]}`, etc.). A malicious value that ever
reached the DB through a non-strict-regex path (whale 13F XML, OGE filings,
admin-editable alert rule names) would render unescaped in subscribers'
inboxes.

*Fix (2026-05-27):* Added an `_e()` helper in `email_sender.py` wrapping
`html.escape(value, quote=True)`. Every interpolated DB-sourced value in the
report-email template goes through it (ticker, signal, price, reason,
insiders list, period label, date, bullish/bearish chips). `alert_engine.py`
does the same with a local `_html.escape(...)` call on ticker and message.
The watchlist recovery email also escapes the minted token (already
URL-safe, but defensive).

---

### ✅ HTML injection in LineChart tooltip
**`frontend/src/components/LineChart.tsx`** — `renderTooltip` set
`tooltip.innerHTML` with template-string interpolation of `label`, which
flows from a series prop whose source includes ticker symbols read from
the DB. Same XSS class as the email-template issue.

*Fix (2026-05-27):* Added a local `htmlEscape()` helper (replaces
`& < > " '`). Both `label` and `dateStr` go through it before
interpolation. `StockChart` was already safe (only numeric values
interpolated), but `LineChart`'s `dateStr` is now also escaped for
consistency.

---

### ✅ Recovery rate limit was per-IP only
**`backend/routers/watchlist.py`** — the recovery throttle bucketed by IP
(3/hr/IP). An attacker cycling IPs could spam a victim's inbox.

*Fix (2026-05-27):* Added a parallel per-email throttle
(`_recover_email_hits`, 3/hr/email). When tripped, the endpoint returns
the same 200 response as a successful send — no information leakage
about whether a hit was throttled, unknown-email, or actually delivered.
Per-IP throttle remains in place as the first line; per-email is the
catch-all for distributed abuse.

---

### ✅ WatchlistOwner orphan rows accumulated
**`backend/models/watchlist.py`** — when a user added then removed all
their tickers, or when a recovery rotation went unused, the
`WatchlistOwner` row (with valid `token_hash`) lived in the DB forever.
Tokens never expire on their own.

*Fix (2026-05-27):* New scheduler job `_watchlist_orphan_cleanup_job`
runs weekly (Sundays 03:30 ET). Deletes `WatchlistOwner` rows where
(a) no `WatchlistItem` exists for that email and (b) the row is dormant
(`last_used_at` >180 days ago, or never used and `created_at` >180 days
ago). Active accounts are never touched. Verified registered in scheduler
startup log.

---

### ✅ persistent_cache opened a fresh connection per call
**`backend/services/persistent_cache.py`** — `cache_get` / `cache_set` /
`cache_delete_expired` each opened a `SessionLocal()` and explicitly
closed it in a try/finally. Worked, but the try/except + close pattern
was noisy and risked leaks if exceptions fired between create and the
try block.

*Fix (2026-05-27):* Switched all three to `with SessionLocal() as db:`
context-manager form. SQLAlchemy's `Session.__exit__` calls `.close()`
unconditionally — same connection reuse semantics, less code, no
risk of a leak between `db = SessionLocal()` and the `try`.

---

### ✅ `javascript:` URLs in external href attributes
**`frontend/src/pages/News.tsx`** (news link), **`Fed.tsx`** (OGE source +
official disclosures), **`Ticker.tsx`** (news links), **`Filings.tsx`**
(SEC index), **`AdminConfig.tsx`** (admin-supplied key-doc links) —
each bound `href={someUrl}` from a DB/feed source. React 18 emits a
warning for `javascript:` URLs but still renders them — a click would
execute. Narrow surface (requires feed compromise or admin malice) but
trivially mitigated.

*Fix (2026-05-27):* New `frontend/src/lib/safeUrl.ts` exports
`safeHref(url)` — accepts only `http(s)://`, `mailto:`, and same-origin
paths (`/...` or `#...`); everything else (including `javascript:`,
`data:`, `vbscript:`, `file:`, empty) returns `"#"`. All six external
href bindings updated to `safeHref(url)`. Typecheck and 69/69 tests
pass.

---

## ✅ Fixed during the initial audit pass (2026-05-19)

- **`frontend/src/pages/Config.jsx`** — `loadKeys()` had no `.catch()`, so a
  non-admin visiting Settings hit a silent 401 and saw an empty, unexplained
  "API Keys" section. Now catches the error and renders an "Admin access
  required — log in to the Admin Panel" message.
- **`backend/routers/config.py`** — `list_subscribers` docstring claimed
  `?email=` bypassed admin auth. It does not (`require_admin` always runs); the
  unauthenticated self-service route is `/config/subscribers/lookup`. Docstring
  corrected.
