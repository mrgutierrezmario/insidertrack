# Checkpoint — 2026-09-19 (data model + coverage pass)

> Earlier checkpoints (2026-05-18, 2026-09-16) are in git history; CHANGELOG.md has the summary.

Live at **https://mgnts-stock-tracker.tail3659a6.ts.net**, deployed via
`deploy/start.sh` (needs `DOCKER_CONFIG` pointing at an empty `{}` config from
the dev container — see memory note). Branch `main` is pushed; CI runs on push.

> Commit hashes were rewritten late on 2026-09-19 (attribution trailers
> scrubbed from all history, force-pushed); any hash quoted below or in older
> notes no longer resolves. Commits carry no attribution trailers from now on.

## What changed today

| Area | Change |
|---|---|
| Politicians | **Everyone tracked by default** (`is_tracked` default true, one-shot migration flipped existing rows). Untracking = admin "mute". The signal universe went from Pelosi's tickers to every ticker traded in 45 days (~139). |
| Trades | New columns `owner` (self/spouse/child/joint), `asset_type` (stock/option/other), `direction` (buy/sell/NULL), `amount_low/high`, `filing_id`, `amends`. `services/trade_semantics.py` is the single source of those rules. **Options follow their contract** (long call / short put = bullish); unknown contracts, bonds, exchanges are neutral. All consumers filter on `direction`. |
| Score | **v3**: Smart money 20 + Congress 30 (dollar-weighted × member `skill_factor`) + Corporate/Form 4 25 + Momentum 25 − Risk 20. Sentiment (a constant 5/10 on the AV free tier) and the fundamentals stub removed. `signal_outcomes.score_version` recorded; Outcomes stats default to the current version. |
| Track record | `services/track_record.py`: every stock buy measured from first close after disclosure to 30/60/90 d vs SPY; `GET /politicians/{id}/track-record`, section on the politician page. Weekly Sunday 04:30 ET `skill_refresh` maps each member's 90-day beat-SPY rate to `politicians.skill_factor` 0.5–1.5 (×1 under 10 buys). |
| Alerts | 15 new events per rule per run, then one overflow summary event. Email was already a per-run digest. `fed_trade` type removed. |
| Fed | Roster only, seeded at startup; no-op job, `/fed/sync` and its button removed. |
| Backups | `deploy/backup.sh` / `backup-setup.sh` / `restore.sh` + launchd plist ported from lecture-note-app. Local half verified; **off-site not activated** until `deploy/backup-setup.sh` is run on the Mac. |
| Startup | Signal cache warmed in a background thread (first request 7 s → 1.4 s). Phone drawer footer carries the business name. |
| Ingest | House disclosure_date = Clerk's filing date (PTR notification dates are hand-typed). Implausible trade dates (future, pre-2012, after filing) rejected. Dedup key includes amount bracket. **Senate amendments** replace the report they amend (title "… for MM/DD/YYYY (Amendment N)"); `repair_senate_amendments()` handles history. |
| Backfill | `POST /trades/backfill?since=&until=&reparse=` (admin, background, progress in Admin → Data sources). `reparse=true` re-fetches processed filings and refreshes rows in place. Loaded 2025-01-01 → today: 698 Senate + 6,396 House. |
| Health | `services/source_health.py`: per-source ok/stale/failing in `/health` ("data"), Admin → Data sources panel with **Run now** per source, daily 09:00 ET email to `MAIL_ADMIN_TO` when something's wrong. Senate/House syncs isolated from each other; manual Form 4 / 13F syncs now background. |
| Ops | GitHub Actions CI (backend w/ Postgres, frontend, image build, nightly). Migration failures logged instead of swallowed. `AI_DAILY_CAP` (150/day) on site-key AI notes. README rewritten to match. |
| Data cleanup | 6 seed trades with no filing removed; duplicate "Tommy Tuberville" merged into "Thomas H Tuberville". All 9,0xx trades now carry a `filing_id`. |
| Tests | 248 backend (was 149) + 70 frontend. New: trade_semantics, source_health, form4/edgar parsers, outcome_tracker, alert_engine, backfill/amendment/re-parse helpers. |

## Live data (end of session)

- 14,437 congressional trades, 2,038 tickers, 169 members with trades (234 member records), Jan 2023 → now; 18,459 Form 4 rows / 678 tickers; 842 13F positions (Q2-2026).
- Re-parse of 2026-05 → now done (317 pre-May rows still have unknown owner — a re-parse of 2025-01 → 2025-04 would clear them). Backfill 2023–2024 done (1,193 Senate + 4,322 House).
- First `skill_refresh` was run manually on 2026-09-19 evening; the weekly job takes over Sunday.

## Running backend tests from the dev container

Local Python is 3.14 and can't install the pinned deps. Use the app image:
throwaway `postgres:18-alpine` on a user network + `tar cz app/ui_backend | docker run -i … stock-tracker-app:latest` + `pip install pytest` + `python -c 'from database import init_db; init_db()'` + `pytest -q`. Bind mounts of dev-container paths are refused by Docker Desktop, hence the tar pipe.

## Gap list — 2026-09-19 evening (worked in this order)

| # | Gap | Status |
|---|---|---|
| 1 | Senate paper filings (GIF scans on EFD) read by the vision model | **done** — verified to the model call; Gemini free-tier quota was spent, first real readings at the next 8 AM sync |
| 2 | Paper rows: link to the filing + admin "Remove misread row" | **done** (`filing_url` on every trade, `DELETE /trades/{id}`) |
| 3 | Backfill 2021–2022 | **running** at session end (started 21:42 UTC; `GET /jobs/running` shows progress) |
| 4 | First market-wide Form 4 run; Insiders page at that size | tomorrow 6:30 — check row count and page load |
| 5 | Smart money weighted by position conviction; first-quarter positions neutral | **done** — score **v4** |
| 6 | Sentiment/News: no source | **done** — Google News RSS headlines when no AV key (or quota spent); sentiment labels only with AV |
| 7 | Track record for sells | **done** (down after the sale = the good call) |
| 8 | Member leaderboard | **done** — `/leaderboard`, from the stored weekly skill numbers |
| 9 | Alert types: cluster buy, skilled-member buy | **done** |
| 10 | Review the email reports after the universe change | tomorrow's morning report |
| 11 | Verify the off-site half of the backup | tomorrow after 03:00: `deploy/state/backups/backup.log` should end "Off-site copy up to date" |
| 12 | Error tracking beyond container logs | **done** — `errors_24h` in `/health`, included in the 9 AM email when non-zero |
| 13 | Single uvicorn worker shares scheduler + syncs + requests | noted; split only if 8:00–8:15 feels slow |
| 14 | Deploy guard | **done** — `deploy/start.sh` refuses to restart under a running job (`--force` overrides); `GET /jobs/running` |

Skill refresh: interrupted by deploys four times today; the final run started
21:42 UTC alongside the backfill. Until it finishes, some members are at
×1.00 and the leaderboard is partial (65 weighted of ~170 with buys).

### Late additions (same evening)
- **UI consistency pass**: one date format (`lib/format.ts`), chamber labels, sentence-case labels, Dashboard tile reads "N bullish · M bearish", chip lists capped at 18 with "+N more", plainer nav hints.
- **Duplicate members merged**: the Clerk's index spells one person several ways; identity is now the bioguide id (roster, incl. nicknames) or a normalized name key; `merge_duplicate_politicians()` runs after every sync. 14 records folded on 2026-09-19; 188/284 members carry a bioguide id (the rest left Congress).

### Still open after this batch
- Senate paper readings unverified end-to-end (quota); House paper verified (22 rows, spot-checked).
- Sentiment is headline-only without an AV key; no scoring use either way.
- Paper filings: a paper *amendment* is stored as a normal filing (the model can't tell what it amends).
- Track-record weights apply only to Congress; 13F holders have no track record of their own.
- No "re-check this paper row" flow beyond delete.

## Deployment gotchas (from the 2026-09-16 rebuild; still true)

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
