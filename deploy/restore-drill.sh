#!/bin/bash
# Restore drill: prove a backup actually restores, without touching the live stack.
#
#   deploy/restore-drill.sh                 newest local bundle
#   deploy/restore-drill.sh --from-remote   fetch the off-site copy first (what a
#                                           real disaster recovery would do)
#   deploy/restore-drill.sh --keep          leave the drill stack running to poke at
#   deploy/restore-drill.sh --notify        email MAIL_ADMIN_TO if it fails (the
#                                           monthly launchd job runs
#                                           --from-remote --notify)
#
# Restores the newest bundle into a throwaway Compose project ("stock-drill":
# its own volumes, no Tailscale — a placeholder holds the network slot), boots
# the app on it, checks the data and the app's health, and tears everything
# down. The drill runs on an internal-only network: the restored database holds
# the real API keys and subscriber list, and the app's startup backfill and
# scheduler would otherwise call Alpha Vantage / the AI providers and could
# send email. With no route out, those fail harmlessly.
set -euo pipefail
cd "$(dirname "$0")"
DRILL=stock-drill
PROJECT=stock-tracker
PGUSER_=stockuser; PGDB_=stocktracker
BACKUP_DIR="${BACKUP_DIR:-$PWD/state/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-stock-tracker-backup:}"
FROM_REMOTE=0; KEEP=0; NOTIFY=0
for arg in "$@"; do case "$arg" in --from-remote) FROM_REMOTE=1 ;; --keep) KEEP=1 ;; --notify) NOTIFY=1 ;; esac; done

log() { echo "[drill $(date '+%Y-%m-%d %H:%M:%S')] $*"; }
REASON="exited early (see the log)"
fail() { REASON="$*"; echo "[drill] FAILED: $*" >&2; exit 1; }
# One value from the live deploy/.env. Read, never exported: exported values
# would override the drill's own env file in every compose call.
live_env() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed "s/^[\"']//; s/[\"']\$//"; }
# Same mail path as backup.sh: the app's own account, to MAIL_ADMIN_TO.
notify_failure() {
  local user pass to from
  user=$(live_env MAIL_USERNAME); pass=$(live_env MAIL_PASSWORD)
  from=$(live_env MAIL_FROM); from=${from:-$user}
  to=$(live_env MAIL_ADMIN_TO); to=${to:-$from}
  [ -n "$user" ] && [ -n "$pass" ] && [ -n "$to" ] || return 0
  printf 'From: %s\nTo: %s\nSubject: InsiderTrack restore drill FAILED on %s\n\n%s\n\nLog: deploy/state/backups/restore-drill.log\n' \
    "$from" "$to" "$(hostname)" "$REASON" |
    curl -s --url "smtps://smtp.gmail.com:465" --mail-from "$from" --mail-rcpt "$to" \
      --user "$user:$pass" -T - >/dev/null 2>&1 || true
}

WORK=$(mktemp -d)
# Compose override: a placeholder in the tailscale slot (the app shares its
# network namespace), and the project's network made internal — no internet.
cat > "$WORK/override.yml" <<'EOF'
services:
  tailscale:
    image: busybox:stable
    entrypoint: ["sh", "-c", "sleep infinity"]
    environment: !reset {}
    ports: !reset []
networks:
  default:
    internal: true
EOF
DC="docker compose -p $DRILL -f compose.yml -f $WORK/override.yml --env-file $WORK/drill.env"
cleanup() {
  status=$?
  if [ $KEEP = 1 ] && [ $status -eq 0 ]; then
    log "Drill stack left running (--keep) — remove with:"
    log "  docker compose -p $DRILL -f deploy/compose.yml down -v --remove-orphans"
  else
    log "Tearing down the drill stack..."
    $DC down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
  if [ $status -eq 0 ]; then
    log "PASSED — the backup restores cleanly."
  else
    echo "[drill] exit $status" >&2
    [ $NOTIFY = 1 ] && notify_failure
  fi
  exit $status
}
trap cleanup EXIT

# ── Bundle ────────────────────────────────────────────────────────────────────
if [ $FROM_REMOTE = 1 ]; then
  command -v rclone >/dev/null || fail "rclone is needed for --from-remote"
  log "Fetching the off-site copy..."
  rclone copy "$RCLONE_REMOTE" "$WORK/remote" --include 'daily/**' --transfers 8 -q \
    || fail "could not fetch the off-site copy from $RCLONE_REMOTE"
  SRC="$WORK/remote"
else
  SRC="$BACKUP_DIR"
fi
BUNDLE=$(ls -1t "$SRC"/daily/$PROJECT-*.tar.gz 2>/dev/null | head -1)
[ -n "$BUNDLE" ] || fail "no bundle under $SRC/daily"
tar -C "$WORK" -xzf "$BUNDLE" || fail "bundle $(basename "$BUNDLE") does not extract"
STAGE=$(ls -d "$WORK"/$PROJECT-*)
log "Bundle: $(basename "$BUNDLE")"
for f in db.sql.gz env tailscale-state.tar.gz; do [ -s "$STAGE/$f" ] || fail "bundle is missing $f"; done

# The bundle's .env gives the drill the DB password the dump expects. Mail
# settings and the Tailscale key are dropped (the network is internal anyway).
grep -v '^\(TS_AUTHKEY\|MAIL_[A-Z_]*\|COMPOSE_PROFILES\)=' "$STAGE/env" > "$WORK/drill.env"
grep -q '^DB_PASSWORD=.' "$WORK/drill.env" || fail "the bundle's env has no DB_PASSWORD"

# ── Tailscale identity ────────────────────────────────────────────────────────
tar -tzf "$STAGE/tailscale-state.tar.gz" | grep -q 'tailscaled.state' \
  || fail "the Tailscale identity in the bundle has no tailscaled.state"

# ── Database ──────────────────────────────────────────────────────────────────
log "Starting drill postgres (project $DRILL, internal network)..."
out=$($DC up -d postgres tailscale-config tailscale 2>&1) || fail "drill postgres did not start: $(echo "$out" | grep -iE 'error|denied' | head -3)"
for i in $(seq 1 60); do $DC exec -T postgres pg_isready -q -U "$PGUSER_" -d "$PGDB_" && break; sleep 1; done
$DC exec -T postgres pg_isready -q -U "$PGUSER_" -d "$PGDB_" || fail "postgres did not start"
log "Restoring the database..."
gzip -dc "$STAGE/db.sql.gz" | $DC exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -q -v ON_ERROR_STOP=1 -o /dev/null \
  || fail "the database dump did not restore"

# ── App ───────────────────────────────────────────────────────────────────────
log "Starting the drill app (no internet: API calls and mail fail harmlessly)..."
out=$($DC up -d --no-build app 2>&1) || fail "drill app did not start: $(echo "$out" | grep -iE 'error|denied' | head -3)"
HEALTH=""
for i in $(seq 1 90); do
  HEALTH=$($DC exec -T app curl -fs http://localhost:8003/health 2>/dev/null || true)
  echo "$HEALTH" | grep -q '"db":true' && break; sleep 2
done
echo "$HEALTH" | grep -q '"db":true' || { $DC logs --tail=30 app >&2; fail "app not healthy: ${HEALTH:-no answer}"; }

# ── Verify ────────────────────────────────────────────────────────────────────
Q() { $DC exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -tAc "$1"; }
TRADES=$(Q "select count(*) from trades"); MEMBERS=$(Q "select count(*) from politicians")
FORM4=$(Q "select count(*) from form4_transactions"); WHALES=$(Q "select count(*) from whale_positions")
OUTCOMES=$(Q "select count(*) from signal_outcomes"); SUBS=$(Q "select count(*) from email_subscribers")
SETTINGS=$(Q "select count(*) from app_settings"); NEWEST=$(Q "select max(trade_date) from trades")
log "Trades: $TRADES (newest $NEWEST) · members: $MEMBERS · Form 4: $FORM4 · 13F positions: $WHALES"
log "Signal outcomes: $OUTCOMES · subscribers: $SUBS · settings: $SETTINGS"
log "Health: $(echo "$HEALTH" | head -c 120)…"
[ "$TRADES" -ge 1 ] && [ "$MEMBERS" -ge 1 ] || fail "no trades or members came back"
[ "$SETTINGS" -ge 1 ] || fail "no app settings came back (API keys live there)"
echo "$HEALTH" | grep -q '"scheduler":true' || fail "the app's scheduler did not start"
