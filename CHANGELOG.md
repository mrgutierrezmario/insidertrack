# Changelog

All notable changes to InsiderTrack. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The current version lives in the
`VERSION` file and is shown in Settings and at `/health`.

## [Unreleased]

### Added
- **AI Desk**: each morning (8:30 ET) the site's AI model reads the day's disclosures and makes 3–5 directional calls with a horizon and reasoning; every call is stored unedited and scored at its horizon against SPY, with a running hit-rate. Dashboard card + `/ai-desk` page under Signals; admin can generate/regenerate. One provider call a day.
- **Fund track records**: each 13F holder's new/increased positions (and trims/exits, inverted) measured 30/60/90 days after the filing date against SPY; a "Fund track records" ranking on the Whales page and a section on every fund's page. `GET /whales/leaderboard`, `GET /whales/{id}/track-record`; `whale_positions.filed_on` now holds the real SEC filing date.
- Watchlist page shows the AI Desk calls on your own tickers; new alert type **AI Desk call** (threshold = minimum confidence %).
- Readable secondary text: every text token clears WCAG AA in both themes; the Dashboard watchlist card fills its column and scrolls.

## [1.1.0] — 2026-09-19

### Added
- User guide (`/guide`) and privacy page (`/privacy`), linked from Settings, the phone menu and the terms gate.
- Senate paper (scanned) filings read by the vision model, like the House ones; every trade links to its filing; admins can remove a misread paper row.
- Track record for **sales** (a sale was a good call if the stock then fell or lagged SPY) and a **Leaderboard** ranking members by how often their buys beat SPY at 90 days.
- Alert types: insider **cluster buy** (market-wide Form 4) and **skilled-member buy**.
- Google News headlines on the News page when there is no Alpha Vantage key (or its quota is spent).
- `/health` reports unhandled exceptions in the last 24 h; the daily admin email includes them. `GET /jobs/running`; `deploy/start.sh` refuses to restart the app under a running backfill / re-parse / sync / skill refresh (`--force` overrides).

### Security
- Dependency updates for every open Dependabot alert (84, incl. 1 critical): Pillow 12.3, pypdf 6.16, lxml 6.1, python-dotenv 1.2; axios 1.20, React Router 7, Vite 6, Vitest 5. `npm audit` is clean.

### Fixed
- One member record per person: the Clerk's index spells names inconsistently across years and members were matched by exact name, so several people were split across 2–4 records. Identity is now the bioguide id (via the congress-legislators roster, nicknames included) or a normalized name key; existing duplicates were merged.
- Consistent date format and chamber labels throughout; sentence-case labels; the Dashboard's ticker chip lists are capped with a "more" link.

### Changed
- Scoring **v4**: smart money weights each 13F position by its share of the holder's book (5%+ earns a conviction bonus); a holder's first loaded quarter is neutral instead of counting every position as "new".

## [1.0.0] — 2026-09-19

First release: the app as it runs at its public URL, after a full data-model
and coverage pass.

### Data
- Congressional trades from the official sources: House Clerk PTR PDFs and the Senate EFD, daily with a rolling 90-day window, plus a date-bounded **historical backfill** (Jan 2023 → today loaded) and a **re-parse** mode that refreshes already-imported filings with the current parser.
- Every trade records the **owner** (member / spouse / dependent child / joint), the **asset kind** (stock / option / other), the disclosed **dollar bracket** as numbers, and a **direction** — the trade's bet on the ticker. Options follow their contract (long call / short put = bullish); unknown contracts, bonds and exchanges are neutral.
- **Amendments reconciled** in both chambers: Senate amendments replace the report they name; House amendments replace individual transactions by their ID. Only the corrected version is shown (tagged AMENDED).
- **Paper (scanned, handwritten) House filings** — about 13% of PTRs — read by the site's vision model (Claude / Gemini / OpenAI), stored with the model's confidence and tagged PAPER · AI-READ.
- Implausible dates rejected at ingest; House disclosure dates taken from the Clerk's filing date.
- **Corporate insiders (SEC Form 4)**: per-ticker history for the congressional universe plus a **market-wide daily feed** of every Form 4 filed (open-market buys and sells), with a **Cluster buys** table (2+ insiders buying) on the Insiders page.
- **Institutional 13F holdings** for 21 discretionary managers (Berkshire, Soros, Bridgewater, Pershing, Tiger Global, Duquesne, Appaloosa, Baupost, Third Point, Elliott, Coatue, Lone Pine, Viking, Greenlight, Trian, Starboard, Altimeter, Icahn, Renaissance, Scion, ARK), synced weekly.
- Every member of Congress with a filing is tracked by default; untracking is an admin mute.

### Signals
- Composite score 0–100 (**v3**): Smart money 20 + Congress 30 (dollar-weighted, scaled by each member's track record) + Corporate insiders 25 + Momentum 25 − staleness penalty 20.
- **Per-member track record**: every disclosed stock buy measured from the first close after disclosure to 30 / 60 / 90 days, against SPY; a weekly job turns each member's beat-SPY rate into a 0.5–1.5× weight on their trades.
- Signal outcomes snapshotted daily and filled at 30/60/90 days; each snapshot records its scoring version so hit-rates compare like with like.
- Alerts (high signal, momentum, politician buy, new whale position, earnings soon, insider cluster buy, skilled-member buy) with a per-rule cap and one digest email per run.
- Investment simulator vs SPY; watchlist with email reports; AI research notes per ticker (site key or bring-your-own), daily-capped.

### Operations
- Docker Compose stack (Postgres 18 + app + Tailscale sidecar) with a fixed public HTTPS URL via Tailscale Funnel; `deploy/start.sh` builds, migrates and restarts.
- **Data-source health**: every scraper records its outcome; `/health` and Admin → Data sources grade each as ok / stale / failing; a daily email when something is wrong. Run-now buttons per source, backfill and re-parse from the admin panel.
- Host-side **encrypted off-site backups** (rclone → Google Drive) with a scripted restore; the app's own nightly `pg_dump` as a second copy.
- CI on every push (backend tests against Postgres, frontend typecheck + tests + build, image build) and nightly; Dependabot with auto-merge for patch/minor updates.
- 272 backend and 70 frontend tests.

## Before 1.0.0

Development began on 2026-05-16 as a congressional-trades feed with a
composite score. Five audit passes in May hardened security, performance and
data integrity; the deployment was rebuilt on Docker + Tailscale Funnel on
2026-09-16 (when the project first became a git repository); AI research
notes gained Claude / Gemini / OpenAI providers on 2026-09-17; and 2026-09-19
brought the data-model pass above. Commit history before that date was
rewritten once to remove attribution trailers; contents are unchanged.

[1.1.0]: https://github.com/mrgutierrezmario/insidertrack/releases/tag/v1.1.0
[1.0.0]: https://github.com/mrgutierrezmario/insidertrack/releases/tag/v1.0.0
