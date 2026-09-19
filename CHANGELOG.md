# Changelog

All notable changes to InsiderTrack. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The current version lives in the
`VERSION` file and is shown in Settings and at `/health`.

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

[1.0.0]: https://github.com/mrgutierrezmario/stock-tracker/releases/tag/v1.0.0
