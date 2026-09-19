# Operator runbook

What the person running InsiderTrack has to do, and when. Everything else in
the stack looks after itself. The README explains *how* each piece works;
this page is only the *to-do list*.

All commands run on the server (the Mac), from the repository folder.

## Nothing to do

These run without you:

| What | When (ET) | How you'd know it failed |
|---|---|---|
| Congressional sync (House Clerk + Senate EFD, rolling 90 days; up to 25 scanned paper filings read by the AI model) | daily 8:00 | Admin → Data sources card turns **stale** / **failing**; 9:00 email to `MAIL_ADMIN_TO` |
| Form 4 corporate insiders (per ticker + market-wide daily index) | daily 6:30 | same |
| 13F whale holdings (21 filers; only does work after each quarterly deadline) | Saturdays 6:00 | same |
| Signal snapshot / outcome fill (the hit-rate data) | daily 7:00 / 7:30 | `/health` → `snapshot_gaps_14d` > 0; gaps are backfilled at the next start |
| Morning / midday / evening analysis + email reports; alert evaluation | 8:00, 12:00, 18:00 (+15 min) | subscribers stop getting mail |
| Member track records → Congress weights (`skill_factor`) | Sundays 4:30 | Politician pages show `×1.00 weight` for everyone |
| Backup (database + `.env` + Tailscale identity → encrypted off-site copy) | nightly 3:00 (launchd on the Mac) | Email to `MAIL_ADMIN_TO`; `deploy/state/backups/backup.log` |
| The app's own `pg_dump` into the `backups` volume (second copy, last 7) | nightly 4:00 | — |
| Container restarts after a crash or reboot; network-namespace watchdog | always | site unreachable |
| Dependabot patch/minor updates | Mondays, merged when CI passes | GitHub email per PR |
| Security advisories | as published | GitHub email + Security tab |

## Weekly (2 minutes, Monday)

1. Open **Admin → Data sources**. Every card should say OK with a recent
   "last new rows". **Stale** means the runs succeed but nothing new has
   arrived for longer than expected — a government site changed under the
   parser. **Failing** means the last three runs raised; the card shows the
   error.
2. Read the Dependabot emails. Green and merged → nothing to do. A PR with a
   comment from the auto-merge workflow is a **major** bump or a Docker
   base-image change; it waits for you (see *When you have 20 minutes*).

## Monthly (10 minutes, first Monday)

Pull the month's merged updates and rebuild the running image:

```bash
git pull
deploy/start.sh
curl -s http://localhost:8013/health     # want "status":"ok"
```

The app restarts for about a minute (Postgres and Tailscale stay up; the
signal cache re-warms on boot). If a security PR merged mid-month, do this
that week instead of waiting.

**Broken after the rebuild?** Return to the last release and rebuild, then
look at the app log:

```bash
git checkout v1.0.0                      # the last tag that worked
deploy/start.sh
docker compose -f deploy/compose.yml logs --tail=100 app
```

Restarting the app kills any backfill / re-parse / skill refresh that was
running — they're idempotent, just start them again afterwards.

## Every few months (5 minutes)

Prove the backup restores — a backup that has never been restored is a
hope, not a backup. On a spare machine (or after `deploy/stop.sh` and
renaming the volumes):

```bash
deploy/restore.sh --from-remote latest
```

It fetches the off-site copy, recreates `deploy/.env`, the database and the
Tailscale identity, and starts the stack. Check `/health` and that the
Dashboard shows trades.

## When you have 20 minutes

A Dependabot PR that was **not** auto-merged (major bump, or a base image):
build the candidate and run it before merging.

```bash
git fetch origin && git checkout <the dependabot branch>
docker build -t stock-tracker-app:candidate -f deploy/Dockerfile .
deploy/start.sh                          # rebuilds from the checked-out code
curl -s http://localhost:8013/health && open http://localhost:8013
git checkout main && deploy/start.sh     # back to main either way
```

Healthy → merge the PR on GitHub. Anything else → close it with a comment
saying what failed; Dependabot will not reopen it.

## Twice a year

- **After each 13F deadline** (mid-February, May, August, November): Admin →
  Data sources → 13F card should show new rows within a week. If not, hit
  Run now.
- **January**: update the copyright year in `LICENSE` and the README footer;
  run **Backfill history** for the year that just ended so it's complete.
- Check the Tailscale machine still has **key expiry disabled** (admin
  console → the machine).

## When the site is down

1. Is the Mac on and signed in? (A reboot needs Docker Desktop running; it
   starts at sign-in.)
2. `docker compose -f deploy/compose.yml ps` — everything should say
   `running`/`healthy`. Something restarting in a loop →
   `docker compose -f deploy/compose.yml logs --tail=100 <service>`.
3. `curl -s http://localhost:8013/health` — `degraded` names the part that is
   failing (`db` or `scheduler`).
4. Reachable locally but not from the internet → Tailscale:
   `docker compose -f deploy/compose.yml logs --tail=50 tailscale`, and check
   the machine in the Tailscale admin console. If the Tailscale container
   restarted, the app notices within ~45 s and restarts itself.
5. Still stuck → `deploy/stop.sh && deploy/start.sh` restarts the whole stack
   without touching data.

## When data looks wrong

- **A member's trades look duplicated or an amount is off** → Admin → Data
  sources → Backfill history with **re-parse** ticked over that filing's
  dates. It re-fetches the filings and refreshes rows in place.
- **Scores all neutral / Form 4 sub-score 12 everywhere** → the Form 4 sync
  hasn't run for the current universe; Run now on the Form 4 card.
- **A scanned (paper) filing read wrongly** → the row is tagged PAPER ·
  AI-READ; delete it from the database or lower `PAPER_MAX_PER_RUN` to 0 in
  `services/paper_ptr.py` to stop reading paper filings altogether.

## When data is lost

Disk died, wrong thing deleted, machine replaced:

```bash
deploy/restore.sh latest                 # from the local copy
deploy/restore.sh --from-remote latest   # from the off-site copy (new machine)
```

The restore needs the backup passphrase (password manager) and, on a new
machine, `deploy/backup-setup.sh` first to reconnect the off-site remote.

## Access

- The admin password is `ADMIN_PASSWORD` in `deploy/.env`; sessions last an
  hour. Change it there and `deploy/start.sh`.
- AI keys (Claude / Gemini / OpenAI) live in Admin → AI research notes, not in
  the repo. `AI_DAILY_CAP` in `deploy/.env` bounds what the site's keys can
  spend on research notes per day; paper-filing readings use the same keys.

## Where things live

| | |
|---|---|
| Secrets and config | `deploy/.env` (git-ignored) |
| Backups, local copy | `deploy/state/backups/` |
| Backups, off-site | the rclone remote `stock-tracker-backup:` (Google Drive, encrypted) |
| Backup schedule | `~/Library/LaunchAgents/com.mgnetwork.stock-tracker-backup.plist` |
| Rollback DB snapshots | `deploy/state/*.dump` (restored automatically only into an empty database) |
| App log | `docker compose -f deploy/compose.yml logs app` |
| Version running | Settings footer, or `/health` |
