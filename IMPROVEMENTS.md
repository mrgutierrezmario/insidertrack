# InsiderTrack — Improvement Opportunities (2026-05-19)

Non-bug enhancements identified during the full-codebase audit. These are
ordered roughly by impact-to-effort. None are blocking; the app is functional.
Items marked ✅ have been implemented.

---

## Backend architecture

### ✅ 1. Compute the signal set once and share it
~~`technical_signals()` was recomputed independently by four callers.~~

*Done (2026-05-19):* Module-level `_signals_cache` with a 5-minute TTL added
to `signals.py`. All four callers share one result per window. See AUDIT_GAPS.md.

### ✅ 2. Batch the per-ticker queries in `signals.py`
~~Per-ticker `_smart_money_score`, `_risk_penalty`, and filing-date queries.~~

*Done (2026-05-19):* `_compute_technical_signals` now pre-fetches all whale
positions, all risk-penalty trades, and all latest filing dates in 3 batch
queries before the ticker loop. See AUDIT_GAPS.md.

### ✅ 3. Add FK indexes
~~Add indexes on `trades.politician_id`, `whale_positions.holder_id`, and
`fed_trades.official_id`.~~

*Done (2026-05-19):* Three `CREATE INDEX IF NOT EXISTS` statements added to
`_apply_migrations()` in `database.py`. Idempotent — picked up automatically
on next restart.

### ✅ 4. Replace in-memory caches with a bounded/persistent store
~~`market_data.py`'s `_cache` / `_history_cache` reset on every restart, losing
the warmed price cache.~~

*Phase 1 (2026-05-19):* eviction added so the in-memory dicts don't grow
unboundedly — `_cache_set` / `_history_cache_set` sweep expired entries past
500 keys.

*Phase 2 (2026-05-27):* Two-tier cache shipped. L1 is the existing in-memory
dict (sub-microsecond hot path). L2 is a new `market_cache` Postgres table
(`cache_key TEXT PK`, `value JSONB`, `expires_at TIMESTAMPTZ`) — survives
process restart. `_cache_get` / `_history_cache_get` now check L1 first;
on miss, consult L2 and hydrate L1 with the remaining TTL. `_cache_set` /
`_history_cache_set` write through both layers. The L2 writes are
fault-tolerant: a Postgres outage logs and degrades to L1-only, so the
hot path never breaks because of a cache backend failure.

Components:
- **`models/market_cache.py`** — `MarketCacheEntry` with a dialect-variant
  column type: `JSONB` in prod, plain `JSON` in test SQLite. Same Python
  API.
- **`services/persistent_cache.py`** — `cache_get(key) -> (value, ttl) | None`,
  `cache_set(key, value, ttl)` with `ON CONFLICT DO UPDATE`, and
  `cache_delete_expired() -> int` for the sweeper.
- **`services/scheduler.py`** — hourly `market_cache_cleanup` job
  (`CronTrigger(minute=17)`) that calls `cache_delete_expired()`.
- **`database.py`** migration creates the table + an `expires_at` index
  (sweeper performance).
- **Tests** (`tests/test_persistent_cache.py`, 9 tests) cover round-trip,
  upsert semantics, non-JSON values are swallowed, `delete_expired` only
  touches expired rows, write-through populates L2, L1 wipe → L2 hydration,
  L1 hit doesn't touch L2, and history-cache hydration.

Verified end-to-end against the running backend: after `/signals/` and
`/market/movers` requests, the `market_cache` table holds the daily history
bars and day-scoped movers payload with correct TTLs. Restart confirmed
the data persists across process death.

Backend tests: **112/112 passing**.

### ✅ 5. Scheduler hardening
~~Add `misfire_grace_time` to each job so restarts don't silently drop runs.~~

*Done (2026-05-19):* All 9 cron jobs now receive `misfire_grace_time=600`
(10 minutes). A persistent `SQLAlchemyJobStore` would further guarantee
no-drop restarts but is not yet added.

---

## Code consolidation (DRY)

### ✅ 6. Extract a shared `_tracked_tickers` helper
~~The same query is duplicated in `routers/insiders.py`, `routers/earnings.py`,
`routers/news.py`, and appears inline in `analyzer.py`, `signals.py`,
`ai_summary.py`, and `scheduler.py`.~~

*Done (2026-05-22):* Created `services/tickers.py` with `tracked_tickers(db)`.
The three router copies in `insiders.py`, `earnings.py`, and `news.py` now
re-export it (`from services.tickers import tracked_tickers as
_tracked_tickers`) — preserves the existing import paths in `scheduler.py` and
`alert_engine.py` without changes. The inline filters in `signals.py`,
`market.py`, `simulator.py`, and `analyzer.py` are different queries (they
need the full Trade row, not just distinct tickers) and are left in place.

### ✅ 7. Extract a shared CSV-export utility (frontend)
~~`exportCSV()` is copy-pasted with small variations in `Feed.jsx`,
`Insiders.jsx`, `Signals.jsx`, `Activity.jsx`, `Outcomes.jsx`, `Fed.jsx`, and
`Whales.jsx`.~~

*Done (2026-05-22):* Created `frontend/src/lib/csv.js` with
`exportCSV(columns, rows, filenameBase)`. All 7 pages now define a thin
page-specific wrapper (`exportWhalesCSV`, `exportFedCSV`, etc.) that calls
the shared helper. Inline `Blob`/`URL.createObjectURL` boilerplate removed
from every page.

### ✅ 8. Centralize theme constants (frontend) — module created, migration partial
~~Colors and inline style objects repeated across every page.~~

*Done (2026-05-24):* Created `frontend/src/lib/theme.js` exporting:
- `C` — semantic color tokens (`C.surface`, `C.text`, `C.success`, ...)
- `card`, `cardLg`, `input`, `buttonPrimary`, `buttonGhost` — shared style objects
- `LABEL_COLORS` (Strong Watch / Watch / Neutral / High Risk / Avoid)
- `OUTCOME_COLORS` (UP / DOWN / FLAT)

Eliminated all 4 duplicated `LABEL_COLORS = { ... }` definitions
(`Outcomes`, `Signals`, `Watchlist`, `Politician`) and all 3 duplicated
`card` style objects (`Alerts`, `Insiders`, `Whale`) — they now import from
`theme.js`.

*Mechanical sweep complete (2026-05-27):* swept every bare hex literal that
maps to an existing token across `src/pages/` and `src/components/`. Before:
~1,077 hex sites; after: 55 (one-off colors like `#7c3aed`, `#fca5a5`,
`#1a2540` — those would need new tokens in `theme.ts` rather than a swap to
existing ones, deferred). The sweep also added the `C` import to 37 files
that didn't have it. `npm run typecheck` clean, `npm test` 69/69, `npm run
build` clean. Hex inside template strings (21 sites) intentionally left for
a separate pass — they're harder to detect with regex and lower-value.

### ✅ 9. Centralize localStorage keys
~~`insidertrack_email` is referenced as a literal in some files and via an
`EMAIL_KEY` constant in others (`Earnings.jsx`). Same for the admin token key.~~

*Done (2026-05-22):* Created `frontend/src/lib/storage.js` exporting
`EMAIL_KEY`, `ADMIN_TOKEN_KEY`, and `ADMIN_SESSION_KEY`. All consumers
(`WatchlistButton.jsx`, `Watchlist.jsx`, `Earnings.jsx`, `AdminConfig.jsx`,
and `api.js` re-export) now import from there — literal strings removed.

---

## API & data quality

### ✅ 10. Surface data-source provenance
~~Demo prices were served silently with no indicator beyond the Dashboard chart.~~

*Done (2026-05-19):* `get_current_price(ticker, with_meta=True)` returns
`{"price": float, "is_demo": bool}`. Simulator response includes `is_demo`;
each signal result includes `is_demo` derived from the price history `_demo`
flag. Frontend can read these to render a badge. See AUDIT_GAPS.md.

### ✅ 11. Add pagination to unbounded list endpoints
~~`/whales/`, `/politicians/`, `/alerts/rules`, and `/news/feed` return full
lists.~~

*Done (2026-05-24):* All four endpoints now accept bounded `limit` /
`offset` query params (`Query(default=200, ge=1, le=500)` for the
list endpoints; `default=30, le=100` for `/news/feed`). Responses still return
a plain array — full `+1 fetch` / `has_more` shape upgrade is deferred to
avoid a coordinated frontend migration, but the unbounded-growth path is now
closed at the API layer.

### ✅ 12. Global exception handler + structured errors
~~Add a FastAPI exception handler that returns a consistent error shape and logs
unexpected exceptions.~~

*Done (2026-05-24):* Three handlers registered in `main.py`:
- `StarletteHTTPException` → preserves the status code, wraps the detail
- `RequestValidationError` → 422 with the structured error list
- `Exception` (catch-all) → 500, logs the traceback with the request id

All responses share the shape
`{"error": str, "detail": str|dict|list, "request_id": str}` and include the
same id in the `x-request-id` response header so callers can quote it when
filing a bug.

### ✅ 13. External-API resilience (yfinance)
~~Wrap yfinance / Alpha Vantage / EDGAR calls with explicit timeouts and a small
retry/backoff.~~

*Done (2026-05-22):* Added `_yf_call(fn, *, retries=2, backoff=0.4)` to
`market_data.py`. All three yfinance call sites (`get_current_price`,
`get_price_history`, `get_ticker_info`) now go through it. Failures retry
with exponential backoff (0.4s, 0.8s) before falling through to Alpha Vantage
or demo data. Alpha Vantage / EDGAR / FRED already use `httpx.Client(timeout=...)`
— no changes needed there.

---

## Auth & security hardening

### ✅ 14. Move admin auth to httpOnly cookies
~~Replace the `sessionStorage` admin token with a httpOnly, Secure, SameSite
cookie issued by `/access/admin/verify`. Removes the XSS token-theft vector.~~

*Done (2026-05-19):* `POST /access/admin/login` sets an httpOnly cookie
(`admin_token`, `samesite=lax`, `max_age=3600`). `require_admin` checks the
cookie first, then falls back to the `X-Admin-Token` header. `api.js` uses
`withCredentials: true` and no longer injects the real token via a request
interceptor — only a non-sensitive `"1"` flag lives in `sessionStorage` for
UI-visibility gating. See AUDIT_GAPS.md.

### ✅ 15. Constant-time secret comparison
~~Use `hmac.compare_digest` for the admin password and token checks in
`access.py`.~~

*Done (2026-05-19):* All secret comparisons in `access.py` and `config.py`
use `hmac.compare_digest`.

### ✅ 16. Verify ownership on subscriber mutations
~~Require the subscriber's email (or a lookup token) on PATCH/DELETE so a user
can only modify their own subscription.~~

*Done (2026-05-19):* `PATCH /config/subscribers/{id}` and
`DELETE /config/subscribers/{id}` now require either a matching `email` query
param or a valid admin token. `DELETE /watchlist/{id}` similarly requires the
owner's email.

---

## Testing & tooling

### ✅ 17. Add a backend test suite
~~`pytest` with a test DB fixture. Highest-value targets: signal scoring math
(`_sma`, `_rsi`, sub-score functions), pagination `has_more` logic, and the
fetchers' parsing code (Form 4, 13F XML, OGE).~~

*Done (2026-05-19):* `backend/tests/` — 79 tests covering signal scoring math,
pagination `has_more` logic, cache eviction, and `get_current_price` meta flag.
Run with `python3 -m pytest` from `backend/`. See AUDIT_GAPS.md.

### ✅ 18. Add frontend component tests
~~`vitest` + React Testing Library for the data-heavy pages and the CSV export
util once extracted.~~

*Done (2026-05-24):* Installed `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `@testing-library/user-event`, and `jsdom`.
Added `test` / `test:watch` scripts to `package.json`. `vite.config.js`
now carries the `test` block (`environment: "jsdom"`, `globals: true`,
`setupFiles: "./src/test/setup.js"`).

19 tests across 4 files, all passing:
- **`src/lib/csv.test.js`** (4) — Blob/download flow, quote escaping,
  null handling, dated filename
- **`src/lib/storage.test.js`** (3) — key values, uniqueness, namespace prefix
- **`src/lib/theme.test.js`** (5) — palette presence, hex validity, shared
  style objects reference `C`, LABEL_COLORS/OUTCOME_COLORS coverage
- **`src/components/WatchlistButton.test.jsx`** (7) — idle render, modal flow,
  localStorage path, success/error/already-watching states, email validation,
  case-normalisation

Run with `npm test` (one-shot) or `npm run test:watch`.

*Extended (2026-05-24):* Added `src/pages/Outcomes.test.jsx` — 8 page-level
tests covering header rendering, resolved-vs-pending row display, the new
`fills YYYY-MM-DD` projected date logic (verifies signal_date + 30/60/90
math), ticker/resolved filter wiring, empty state, and the Snapshot/Fill
trigger buttons.

The Outcomes test surfaced and fixed a small bug along the way: the table
header row used the column label as the React `key`, and `"+%"` appeared 3
times causing a duplicate-key warning. Keys are now stable column ids.

*Extended again (2026-05-24):* Added `src/pages/Signals.test.jsx` — 10
page-level tests covering header + fetch on mount, card rendering for
BULLISH/BEARISH/NEUTRAL labels, default sort-by-score, ticker search filter,
label-chip filter, signal-chip filter, manual refresh, empty state, RSI
overbought rendering, and sort-dropdown switch to ticker A-Z.

*Extended again (2026-05-25):* Added `src/pages/Whales.test.jsx` — 11
page-level tests covering holder + feed fetch on mount, holder cards with
position counts, all four change badges (NEW / ↑ ADD / ↓ TRIM / ✕ CLOSED /
— HOLD), the conviction-buys banner showing only new/increased tickers,
move-type filter, ticker filter, holder-card click setting `holder_id`,
Clear-filters button, admin-gated Sync button (hidden for non-admin, visible
+ functional when `ADMIN_TOKEN_KEY` is set in sessionStorage), and empty-state.

Total frontend test count: **48 passing across 7 files** (csv, storage,
theme, WatchlistButton, Outcomes, Signals, Whales).

*Extended again (2026-05-25):* Added `src/pages/Activity.test.tsx` — 10
page-level tests covering header + three-source fan-out on mount, source
+ type + ticker filters, newest-first sort, CSV button visibility, empty
state, Clear reset, and Load-more refetch with offset.

*Extended again (2026-05-25):* Added `src/pages/Fed.test.tsx` — 11
page-level tests covering header + officials/trades fetch on mount, board
default tab, regional tab switch, official-click refetch with `official_id`,
ticker + type filters, Clear reset, CSV button, admin-gated Sync (hidden
without `ADMIN_TOKEN_KEY`, visible + functional with it), and empty-trades
state.

Total frontend test count: **69 passing across 9 files** (csv, storage,
theme, WatchlistButton, Outcomes, Signals, Whales, Activity, Fed).

### ✅ 19. Add `.env.example` and a deep health endpoint
~~Document every expected env var in `.env.example`. Add `GET /health` returning
DB connectivity + scheduler status for deployment monitoring.~~

*Done (2026-05-22):* `.env.example` created at repo root (DATABASE_URL,
POSTGRES_*, BACKEND_PORT, FRONTEND_PORT, ALPHA_VANTAGE_KEY, ANTHROPIC_API_KEY,
ADMIN_PASSWORD, MAIL_*), grouped by required/optional. `/health` now executes
`SELECT 1` against the DB, checks `scheduler.running`, and returns
`{"status":"ok"|"degraded", "db": bool, "scheduler": bool}` with HTTP 200 / 503.

---

### ✅ Backend dep hygiene (2026-05-27)
- Removed three unused deps from `backend/requirements.txt`: `alembic` (we
  use a custom `_apply_migrations()` in `database.py`, not alembic),
  `fastapi-mail` (emails go through plain `smtplib`), `asyncpg` (only
  `psycopg2-binary` is in the SQLAlchemy URL). Verified via grep — zero
  imports of any of them.
- Bumped the safe-to-update direct deps to latest:
  `apscheduler 3.10.4 → 3.11.2`, `anthropic 0.102.0 → 0.104.1`,
  `httpx 0.27.0 → 0.28.1`. `fastapi` and `yfinance` intentionally left
  pinned — fastapi 0.111→0.136 has middleware/lifespan breaking changes
  not worth the test surface; yfinance is notoriously fragile and the
  current pin is the known-good version.
- `pip install -r requirements.txt` clean. Backend 112/112 tests pass.
  Live restart smoke-tested: `/health`, `/signals/`, `/market/movers`,
  `/market/macro` all return 200.

### ✅ Frontend route-level code splitting (2026-05-27)
Initial bundle was 428 KB raw / 121 KB gzipped — fine, but a chunk of
that was page code the user might never reach. Switched all 22 pages to
`React.lazy()` + `Suspense` in `App.tsx`. Each page now compiles to its
own chunk (5-17 KB raw / 2-5 KB gzipped), loaded on first navigation.

Result:
- Initial bundle: **428 KB → 240 KB raw (-44%)**, **121 KB → 80 KB gzipped (-34%)**.
- Page chunks: 22 separate files, largest is `AdminConfig` at 17 KB / 4.7 KB
  gzipped. Loading a new page after first visit is one HTTP request for the
  chunk; on a fast connection that's <100 ms and the Suspense fallback
  (`"Loading…"` placeholder) covers it.
- Typecheck clean, 69/69 tests still pass, build clean.

---

## Larger / longer-term

### ✅ 20. TypeScript for the frontend — infrastructure + lib/components migrated
~~Types would catch a class of `undefined` access bugs at build time.~~

*Done (2026-05-25), phase 1:* TypeScript infrastructure is in place and the
shared modules + a flagship component are fully typed. The rest is left as
incremental migration — `.jsx` and `.tsx` coexist (`allowJs: true`), so pages
can move file-by-file without a flag day.

**Infrastructure shipped:**
- `typescript@5` + `@types/node` added as devDeps.
- `tsconfig.json` at frontend root — strict mode, `react-jsx` transform,
  `allowJs: true` / `checkJs: false` (existing .jsx isn't type-checked yet),
  `noImplicitAny`, `noEmit` (Vite handles compilation).
- `npm run typecheck` script wired (`tsc --noEmit`). Zero errors.

**Types layer:**
- `src/types/api.ts` — full domain types for the JSON shapes the backend
  returns: `Politician`, `Trade`, `RiskLevel`, `TechnicalSignal`, `SubScores`,
  `OutcomeRow`, `OutcomeWindow`, `OutcomeStats`, `WhaleHolder`,
  `WhalePosition`, `WhaleChangeType`, `WatchlistItem`, `Health`, plus the
  unions (`SignalLabel`, `SignalDirection`, `OutcomeDirection`, etc.).

**Modules migrated:**
- `lib/csv.ts` — `exportCSV(columns, rows, filenameBase)` typed with
  `CSVCell = string | number | boolean | null | undefined` and `readonly`
  array params. Tighter than the JS contract.
- `lib/storage.ts` — keys narrowed to literal-string types via `as const`;
  exposes a `StorageKey` union.
- `lib/theme.ts` — `C` is `as const` so each token is a literal string;
  `card`, `cardLg`, `input`, `buttonPrimary`, `buttonGhost` typed as
  `CSSProperties`; `LABEL_COLORS` and `OUTCOME_COLORS` use
  `Record<SignalLabel, string>` / `Record<OutcomeDirection, string>` so
  callers get exhaustiveness checks.

**Component migrated as pattern:**
- `components/WatchlistButton.tsx` — full prop types
  (`WatchlistButtonProps`, `EmailModalProps`), `WatchState` union, typed
  event handlers (`KeyboardEvent<HTMLInputElement>`,
  `MouseEvent<HTMLButtonElement>`), typed async returns. Future component
  migrations can copy this shape.

**Verification:**
- `npm run typecheck` → clean
- `npm test` → 48/48 still pass (test files remain `.test.jsx`, exercise the
  new `.ts` modules via runtime imports)

**API client migrated (2026-05-25, phase 1b):**
- `lib/api.js` → `lib/api.ts`. Every endpoint typed with
  `Promise<AxiosResponse<T>>` (`Resp<T>` alias for readability). Response
  shapes pull from `src/types/api.ts` where the backend has a known JSON
  contract; less-touched endpoints currently use `unknown` (intentional —
  callers must narrow, and the types can be tightened incrementally without
  blocking other migrations). Notable typed returns: trades (paginated),
  politicians, signals, outcomes (`OutcomeRow[]`, `OutcomeStats`), whales
  (`WhaleHolder[]`, `WhalePosition[]`), watchlist, alerts (rules + events),
  health, admin login/logout/status. Inline `Subscriber`, `AlertRule`,
  `AlertEvent`, `PaginatedTrades`, `TechnicalSignalsResponse` interfaces are
  scoped to the file — promoted to `types/api.ts` later if other modules
  need them.
- `npm run typecheck` → clean. `npm test` → 48/48.

**App entry + root migrated (2026-05-25, phase 1c):**
- `src/main.jsx` → `src/main.tsx`. Non-null cast on `getElementById("root")`
  — the standard Vite pattern; failing at boot if `#root` is missing is the
  right behaviour. `index.html` updated to reference `/src/main.tsx`.
- `src/App.jsx` → `src/App.tsx`. `linkStyle` typed to return `CSSProperties`
  with a minimal `{ isActive: boolean }` arg (forward-compatible with
  react-router's `isPending`/`isTransitioning` additions). `AlertsLink`:
  `count` typed `number`, `useRef` typed `ReturnType<typeof setInterval> | null`
  with a null-guard in the cleanup function. `ALL_NAV` typed as
  `ReadonlyArray<NavEntry>` so accidental mutation is a compile error.

**Pages migrated (2026-05-25, phase 2):**
- All 22 page files renamed `.jsx` → `.tsx` in one sweep. `index.html` and
  vite-resolved imports continue to work because the file resolver doesn't
  care about extension.
- Strict TypeScript (`noImplicitAny`, `strict: true`) initially produced
  **740 errors** across the pages — almost all from untyped `useState(null)`,
  untyped event handlers, and untyped destructured props.
- Standard incremental-migration checkpoint applied: 19 pages carry
  `// @ts-nocheck — migrated from .jsx; types to be added incrementally.` at
  the top. They build, run, and are exercised by the existing tests; they
  just aren't type-checked yet. Removing the comment one file at a time is
  the path forward.
- 3 pages fully typed end-to-end as the pattern reference:
  - **`NotFound.tsx`** — trivial, no `@ts-nocheck`.
  - **`News.tsx`** — `SentimentLabel` union, `NewsItem` + `NewsFeedData`
    interfaces, `LABEL_STYLE` as `Record<SentimentLabel, …>` for
    exhaustiveness, typed handlers and helpers.
  - **`Earnings.tsx`** — `EarningsItem` + `EarningsData` interfaces, typed
    `useState<EarningsData | null>`, all helper signatures
    (`days: number | null | undefined`).
- Test files also got the `@ts-nocheck` checkpoint — they pass at runtime
  (48/48), but strict-mode null checks + `vi.mock` losing type info would
  need `vi.mocked()` wrappers and null assertions. That's a separate refactor.
- `npm run typecheck` → zero errors. `npm test` → 48/48.

**Components migrated (2026-05-25, phase 3):**
- All 12 .jsx components in `src/components/` renamed to `.tsx`.
- Initial strict-mode error surface: **208 errors** — dominated by
  `SearchBar` (67), `LineChart` (51), `StockChart` (34), `AiSummaryPanel` (16).
- Checkpoint applied to 10 components; **5 fully typed end-to-end**:
  - **`SkeletonCard.tsx`** — `SkeletonCardProps` with `lines: 1 | 2 | 3`
    literal union.
  - **`SignalBadge.tsx`** — `SignalKind = "BUY" | "SELL" | "HOLD"` union;
    `colors` typed as `Record<SignalKind, …>` for exhaustiveness.
  - **`ConfirmModal.tsx`** — full props interface with `KeyboardEvent`
    typing on the global Escape handler.
  - **`ErrorBoundary.tsx`** — `Component<ErrorBoundaryProps,
    ErrorBoundaryState>` with `Error | null` state, typed
    `getDerivedStateFromError` and `componentDidCatch`.
  - **`Disclaimer.tsx`** — `Status` / `SubResult` / `PeriodKey` unions;
    `PERIODS` as `ReadonlyArray<…>`; `periods` state as
    `Record<PeriodKey, boolean>` so mistyped keys are a compile error.
- `WatchlistButton.tsx` was already typed end-to-end in phase 1.
- `npm run typecheck` → clean. `npm test` → 48/48.

**Pages tightened (2026-05-25, phase 4):**
- **`Feed.tsx`** — checkpoint removed. `Filters` interface; `useState<Trade[]>`,
  `useState<Politician[]>`, `useState<Filters>`; generic `set<K extends keyof Filters>`
  so `set("ticker", "AAPL")` is checked at the call site. API client's typed
  `PaginatedTrades` return removed the `"items" in data` runtime probe.
- **`Watchlist.tsx`** — checkpoint removed. Inline `WatchlistRow` interface
  (the `/watchlist/signals` shape isn't in `types/api.ts` yet — promoted later
  if reused). `isValidEmail`, `ChangeChip`, `load`, `remove` all typed.

**More migration (2026-05-25, phase 5):**
- **Pages** typed in this pass: `Simulator.tsx`, `Politician.tsx`, `Whale.tsx`,
  `Config.tsx`, `Insiders.tsx`, `Filings.tsx`, `Alerts.tsx`, `Signals.tsx`,
  `Whales.tsx`, `Ticker.tsx`, `Politicians.tsx`, `Dashboard.tsx`,
  `Activity.tsx`, `Markets.tsx`, `Outcomes.tsx`, `Fed.tsx` — **16 pages**
  moved off `@ts-nocheck` in one push. Common patterns:
  - Typed `useState<T | null>(null)` with the right discriminated state
  - `useParams<{ id: string }>` + `Number(id)` for numeric route params
  - File-local interfaces for endpoints not yet promoted to `types/api.ts`
  - `Record<UnionKey, ...>` for exhaustively-keyed style/meta maps
    (CHANGE_STYLE, TYPE_META, TYPE_STYLE, RISK_META, SIGNAL_META, …)
  - Helper functions cast through `Record<string, T>` for arbitrary key
    lookups when the API may return values outside the declared union
    (e.g. `styleFor()` in Whale.tsx, the inline cast on the SIGNAL_META
    lookup in Signals.tsx)
  - Where the API client typed a domain with a different shape than the
    page needed (e.g. `getAlertRules` → inline `AlertRule`, missing
    `event_count`), promoted via `as unknown as MyShape` rather than
    reshaping the API client in this pass.
  - Trip-up: TS narrowing doesn't propagate across a derived const, so
    patterns like `growthSeries && growth.foo` need `growthSeries && growth
    && growth.foo` or a `growth?.foo` rewrite.
- **Components** typed in this pass: `ChartModal.tsx`, `TradeCard.tsx`,
  `AiSummaryPanel.tsx` — 3 more components moved off `@ts-nocheck`.

**Status after phase 5:**
- `src/pages/` — **all 17 typed** including `AdminConfig.tsx` (the largest
  at 505 lines; types declared upfront made the conversion clean despite
  the ~100-error surface when nocheck was first stripped).
- `src/components/` — **all components typed**, including the chart-heavy
  ones (`ActivityChart`, `StockChart`, `LineChart`, `SearchBar`). Pattern
  for the lightweight-charts components: pin the dynamic-import surface
  as `any` behind eslint-disable comments rather than chasing the library's
  evolving TS declarations; type everything else (props, refs, mapped
  data, touch/keyboard handlers, tooltip helpers) strictly.
- `src/pages/*.test.tsx` — **all test files typed (2026-05-27)**. Swept
  `vi.mocked()` wrappers around every `getX.mockResolvedValue(...)` /
  `.mock.calls` pattern via Perl regex, added `as any` casts on mock
  response data where the real return type is stricter than the test
  fixture needed, added `!` non-null assertions on `closest("tr")` /
  `.parentElement` queries, and `?? ""` on `getAttribute("href")` calls
  that flowed into `RegExp.test()`. **Zero `@ts-nocheck` comments remain
  anywhere in `src/`.**

`npm run typecheck` → clean. `npm test` → 69/69.

### ✅ 21. Reconcile `Config.jsx` and `AdminConfig.jsx`
~~Both touched API-key management and overlapped in responsibility.~~

*Done (2026-05-24):* The API-keys section, the `getSettingsKeys` /
`updateSettingKey` / `clearSettingKey` imports, and the related state/handlers
were removed from `Config.jsx`. The page is now pure self-service: email
lookup, subscription pause/resume/unsubscribe, period toggles. A small pointer
at the bottom directs admins to the Admin Panel for keys, subscribers, and
email diagnostics. ~75 lines and ~half the imports gone.

### ✅ 22. Real FK for `SignalOutcome.politician_id`
~~Column was not a declared `ForeignKey`; `outcomes.py` carried a runtime
fallback subquery for legacy NULL rows.~~

*Done (2026-05-24):* `SignalOutcome.politician_id` is now declared
`ForeignKey("politicians.id", ondelete="SET NULL")` and indexed. An idempotent
DO-block migration in `_apply_migrations()` promotes the constraint on existing
DBs (verified zero orphan rows before adding). The runtime fallback subquery
in `routers/outcomes.py:list_outcomes` was deleted — `politician_id` /
`politician_name` are now read straight from the row. Older rows were already
backfilled by the 2026-05-19 migration, so no rows lose their attribution.

---

## Added in second audit pass (2026-05-19)

### ✅ 23. Use a day-scoped TTL for daily-cadence data
~~`market.py`'s `macro_indicators` and `movers` cache under the generic 5-minute
`CACHE_TTL`.~~

*Done (2026-05-22):* `_cache_set` now accepts an optional `ttl` parameter
(default 5 min). `market_movers` and `macro_indicators` use a
`{name}:{today}` cache key with `ttl=21_600` (6 h). The day-scoped key prevents
cross-day reuse; the longer TTL eliminates the 5-min thrash that was
re-hitting yfinance.

### ✅ 24. Background slow admin-triggered endpoints consistently
~~`/alerts/run` ran `evaluate_alerts` inline while `/outcomes/snapshot`,
`/outcomes/fill`, and `/fed/sync` used `BackgroundTasks`.~~

*Done (2026-05-19):* `POST /alerts/run` now uses
`background_tasks.add_task(evaluate_alerts, db)` and returns
`{"status": "started"}` immediately, consistent with all other manual-trigger
endpoints.

### ✅ 25. Add a Content-Security-Policy header
~~`SecurityHeadersMiddleware` covers framing, MIME sniffing, and referrer policy
but not CSP.~~

*Done (2026-05-19):* `SecurityHeadersMiddleware` now sets a
`Content-Security-Policy` header (`default-src 'self'` with `script-src` /
`style-src` widened for the Vite bundle, `connect-src 'self'` as the key
exfiltration mitigation). `X-XSS-Protection` was also corrected from the
deprecated `1; mode=block` to `0`.

### ✅ 26. Precompute or store trade `risk_level`
~~Filter required over-fetch + Python filtering because the formula couldn't
be expressed in SQL.~~

*Done (2026-05-24):* Added `Trade.risk_level` (`VARCHAR(8)`, indexed). Migration
in `_apply_migrations()` adds the column + index. A new `refresh_risk_levels`
function in `routers/trades.py` walks every trade and writes the current
classification — called at startup (backfill) and by a new
`risk_refresh` scheduler job that fires daily at 05:30 ET. The `/trades`
filter is now a plain SQL predicate (`Trade.risk_level == ...`) — no more
over-fetch, `total` is accurate, and `risk_level` is part of the indexed page
scan. Read path falls back to live `_risk_level(t)` for any row the daily job
hasn't touched yet (fresh inserts between runs).

---

## Added in third audit pass (2026-05-22)

### ✅ 27. Skip demo prices in `snapshot_signals`
~~`snapshot_signals` accepted demo prices, polluting future return %.~~

*Done (2026-05-22):* Rows with `is_demo=True` are skipped, with a warn-level
log line recording the skipped count. See AUDIT_GAPS.md.

### ✅ 28. Unique index on `(ticker, signal_date)` + `ON CONFLICT DO NOTHING`
~~Snapshot idempotency depended on a `count()` precheck, which is racy.~~

*Done (2026-05-22):* Added `ux_signal_outcomes_ticker_date` and rewrote the
insert to use `postgresql.insert(...).on_conflict_do_nothing(...)`. See
AUDIT_GAPS.md.

### ✅ 29. Narrow CORS allowlist + add HSTS
~~CORS listed unused dev ports; no `Strict-Transport-Security` header.~~

*Done (2026-05-22):* CORS reduced to `localhost:8003` plus the ngrok domain;
HSTS header (`max-age=31536000; includeSubDomains`) added. See AUDIT_GAPS.md.

### ✅ 30. Show projected fill date on pending outcomes
~~`OutcomeChip` rendered `pending` with no hint of when it would fill.~~

*Done (2026-05-22):* Pending cells now render `fills YYYY-MM-DD` (computed as
`signal_date + window`). Cells where the fill date has passed but the value is
still null render in amber. See AUDIT_GAPS.md.

### ✅ 31. Snapshot gap detection + retroactive backfill
~~No alerting when snapshots are missed; no retroactive reconstruction.~~

*Phase 1 (2026-05-24):* `detect_snapshot_gaps(db, window_days=14)` lists the
weekdays missing a row. Surfaced in startup logs at WARN and in `/health` as
`"snapshot_gaps_14d": <int>`.

*Phase 2 (2026-05-25):* Full retroactive backfill shipped — gaps are now
reconstructed automatically on startup. Components:

- **Schema** — `SignalOutcome.is_backfilled` boolean (default `false`), added
  via idempotent migration in `_apply_migrations()`.
- **`_compute_technical_signals(db, target_date=None)`** — now time-aware.
  Trades, whale filings, recent-risk trades, and price bars are all filtered
  to `<= target_date`. The 24h price-history cache is reused; the fetched
  window widens to 120 days when computing historically so SMA50/RSI have
  enough lookback. News sentiment can't be reconstructed (Alpha Vantage's
  free tier returns current-only), so historical scores use a neutral
  `sentiments = {}` → defaults to 50 per ticker.
- **`snapshot_signals(db, target_date=None)`** — accepts a target date; sets
  `is_backfilled=True` when it's not today; insert is still idempotent via
  the `(ticker, signal_date)` unique index + `ON CONFLICT DO NOTHING`.
- **`backfill_snapshot_gaps(db, window_days=14)`** — walks the gap list and
  calls `snapshot_signals` for each missing weekday. Returns a small
  summary dict.
- **Startup hook** — `lifespan` now invokes the backfill automatically when
  gaps are detected, logging the summary.
- **Admin endpoint** — `POST /outcomes/backfill?window_days=N` (default 14,
  max 60) triggers a manual backfill in the background.
- **UI** — `Outcomes.jsx` renders a small amber `BF` chip next to the date
  column for backfilled rows, with a tooltip explaining the sentiment
  caveat. `runOutcomeBackfill()` added to `lib/api.js`.

*Limitations (honest accounting):*
1. **News sentiment is approximate** for backfilled rows — uses neutral 50.
   The composite is otherwise faithful (smart-money + insider + momentum +
   risk-penalty are all reconstructible from the persisted Trade and
   WhalePosition rows; fundamentals is a constant 10 stub anyway).
2. **Whale filings dated > target_date are correctly excluded** — but the
   ones we DO use weren't necessarily public-knowledge yet on target_date
   (13F filings have a 45-day disclosure lag). The same is true of the
   live snapshot, so this is consistent rather than worse.
3. **Backfill only covers weekdays in the configured window.** Older gaps
   are preserved as "no row exists" — fixing those would require a manual
   call with a larger `window_days`.
4. **Requires a working price-data source.** The existing `is_demo` skip
   rule (added to keep synthetic prices out of win-rate stats) also fires
   on backfill. In environments where yfinance is blocked AND Alpha Vantage
   is rate-limited, backfill computes signals but skips inserting them
   because every price comes back demo. Log line:
   `Backfill complete: 0 day(s) filled with 0 row(s), N day(s) had no
   scorable tickers`. In production this would behave normally.

### ✅ 32. `fill_outcomes` fetches history once per (ticker, window)
~~Looped `30/60/90` and called `get_price_history(ticker, days=N+10)` per
window — 3× the external calls for any ticker with multiple pending windows.~~

*Done (2026-05-22):* Restructured to pull every pending row across all
windows in a single query (OR over the three `outcome_*` IS NULL conditions),
group by ticker, fetch one 100-day history per ticker, then slice all three
windows from it. External calls cut by up to 67% for any ticker with multiple
pending lookbacks.

### ✅ 33. `technical_signals` price-history fan-out is sequential
~~`_compute_technical_signals` iterates tickers and calls `get_price_history`
serially.~~

*Done (2026-05-22):* `_compute_technical_signals` now uses
`ThreadPoolExecutor(max_workers=8)` to fan out the per-ticker
`get_price_history` calls. Most calls hit the 24h history cache and return
instantly; only cold tickers actually pay the network round-trip, and now in
parallel. Concurrency capped at 8 to stay under upstream rate limits.

### ✅ 34. Win-rate windows are calendar days, not trading days
~~`fill_outcomes` looks up the close on `signal_date + 30 calendar days`.~~

*Done (2026-05-22):* Added `_add_trading_days(start, n)` helper (skips
Saturdays and Sundays). `fill_outcomes` now uses
`_add_trading_days(row.signal_date, days)` for each of the 30/60/90 windows.
US market holidays are not yet accounted for, but the weekend drift that
caused the most obvious mismatches is fixed. The eligibility pre-filter
remains calendar-based (conservative — picks up rows that *might* be ready,
and the per-row trading-day check then gates the actual fill).

### ✅ 35. `start.sh` rebuilds frontend on every run
~~`npm install` and `npm run build` run unconditionally even when nothing in
`frontend/src` has changed.~~

*Done (2026-05-22):* `start.sh` now uses
`find frontend/src frontend/package.json frontend/vite.config.js -newer
frontend/dist/index.html` to detect changes. When nothing newer is found the
install + build steps are skipped and the script reports
"Frontend dist is up to date — skipping build."

### ✅ 36. `/health` is shallow
~~Returns `{"status":"ok"}` without probing the DB or scheduler.~~

*Done (2026-05-22):* `/health` now executes a `SELECT 1` against the DB and
checks `scheduler.running`. Returns `{"status":"ok"|"degraded", "db": bool,
"scheduler": bool}` with HTTP 200 when both are healthy and 503 otherwise.
Suitable as a load-balancer or uptime-monitor probe.

### ✅ 19a. `.env.example`
~~Document every expected env var.~~

*Done (2026-05-22):* `.env.example` created at the repo root with
DATABASE_URL, POSTGRES_*, BACKEND_PORT, FRONTEND_PORT, ALPHA_VANTAGE_KEY,
ANTHROPIC_API_KEY, ADMIN_PASSWORD, and MAIL_* — grouped by required vs.
optional with one-line guidance for each.

### ✅ 37. APScheduler persistent jobstore
~~`misfire_grace_time` handles short blips, but next-run state is lost on
restart.~~

*Done (2026-05-24):* Scheduler now uses `SQLAlchemyJobStore` against the
existing Postgres connection (table: `apscheduler_jobs`). Each job is
registered with a stable `id=` and `replace_existing=True` so the persistent
row is upserted on every startup — the current function reference is always
the one that runs. Next-run state survives restarts, narrowing the
"snapshot/fill gap" risk from item 31.
