#!/bin/bash
# Nightly backup of the InsiderTrack stack — runs on the HOST (the Mac), not in
# a container, so the copy is independent of Docker.
#
#   deploy/backup.sh              back up, prune old copies, sync off-site
#   deploy/backup.sh --no-remote  skip the off-site sync
#
# Saved under $BACKUP_DIR (default deploy/state/backups):
#   daily/stock-tracker-YYYY-MM-DD.tar.gz   Postgres dump (trades, Form 4, 13F,
#                                           signals, outcomes, alerts, watchlists,
#                                           API keys — everything lives in the DB),
#                                           deploy/.env, the Tailscale identity
#   weekly/…                                Sunday's bundle, kept longer
#
# Off-site: if rclone has a remote named $RCLONE_REMOTE (created by
# deploy/backup-setup.sh — an encrypted folder in Google Drive), the backup
# directory is synced there. Restore with deploy/restore.sh.
#
# Schedule with deploy/mac/com.mgnetwork.stock-tracker-backup.plist on a Mac
# (backup-setup.sh installs it), or cron on Linux:
#   0 3 * * * /path/to/deploy/backup.sh >> deploy/state/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"
PROJECT=stock-tracker              # compose project name → volume prefix
PGUSER_=stockuser; PGDB_=stocktracker

BACKUP_DIR="${BACKUP_DIR:-$PWD/state/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-stock-tracker-backup:}"
KEEP_DAILY="${KEEP_DAILY:-14}"
KEEP_WEEKLY="${KEEP_WEEKLY:-8}"
REMOTE=1; [ "${1:-}" = "--no-remote" ] && REMOTE=0

log() { echo "[backup $(date '+%Y-%m-%d %H:%M:%S')] $*"; }
load_env() {
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key=${line%%=*}; val=${line#*=}
    case "$val" in \"*\") val=${val#\"}; val=${val%\"} ;; \'*\') val=${val#\'}; val=${val%\'} ;; esac
    export "$key=$val"
  done < "$1"
}

# Email the operator on failure through the app's own mail account (uses
# MAIL_ADMIN_TO, falling back to the sender), when mail is configured.
[ -f .env ] && load_env .env
notify_failure() {
  local to="${MAIL_ADMIN_TO:-${MAIL_FROM:-${MAIL_USERNAME:-}}}"
  [ -n "${MAIL_USERNAME:-}" ] && [ -n "${MAIL_PASSWORD:-}" ] && [ -n "$to" ] || return 0
  printf 'From: %s\nTo: %s\nSubject: InsiderTrack backup FAILED on %s\n\nStep: %s\nCheck deploy/state/backups/backup.log.\n' \
    "${MAIL_FROM:-$MAIL_USERNAME}" "$to" "$(hostname)" "$STEP" |
    curl -s --url "smtps://smtp.gmail.com:465" --mail-from "${MAIL_FROM:-$MAIL_USERNAME}" --mail-rcpt "$to" \
      --user "$MAIL_USERNAME:$MAIL_PASSWORD" -T - >/dev/null 2>&1 || true
}
STEP=starting; WORK=""
trap 'status=$?; [ -n "$WORK" ] && rm -rf "$WORK"; [ $status -ne 0 ] && { log "FAILED during: $STEP (exit $status)"; notify_failure; }; exit $status' EXIT

command -v docker >/dev/null || { echo "docker not found on PATH" >&2; exit 1; }
$DC ps --status running --services 2>/dev/null | grep -qx postgres || { echo "The stack is not running (deploy/start.sh)." >&2; exit 1; }

DATE=$(date +%Y-%m-%d)
WORK=$(mktemp -d)
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"
BUNDLE="$BACKUP_DIR/daily/$PROJECT-$DATE.tar.gz"
STAGE="$WORK/$PROJECT-$DATE"; mkdir -p "$STAGE"

# ── 1. Database ───────────────────────────────────────────────────────────────
STEP="database dump"; log "Dumping Postgres..."
$DC exec -T postgres pg_dump -U "$PGUSER_" --no-owner --no-privileges "$PGDB_" | gzip -6 > "$STAGE/db.sql.gz"
[ "$(gzip -dc "$STAGE/db.sql.gz" | grep -c 'PostgreSQL database dump complete')" = 1 ] || { echo "pg_dump output is incomplete" >&2; exit 1; }

# ── 2. Secrets and identity ───────────────────────────────────────────────────
STEP="state"; log "Copying .env and the Tailscale identity..."
cp .env "$STAGE/env"
docker run --rm -v "${PROJECT}_tailscale-state:/v:ro" busybox:stable tar -C /v -czf - . > "$STAGE/tailscale-state.tar.gz"

# ── 3. Bundle + prune ─────────────────────────────────────────────────────────
STEP="bundle"
# macOS tar adds ._* resource-fork entries unless told not to.
export COPYFILE_DISABLE=1
tar -C "$WORK" -czf "$BUNDLE" "$(basename "$STAGE")"
log "Bundle: $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
[ "$(date +%u)" = 7 ] && cp "$BUNDLE" "$BACKUP_DIR/weekly/"
prune() { ( ls -1t "$1"/$PROJECT-*.tar.gz 2>/dev/null || true ) | tail -n +"$(( $2 + 1 ))" | xargs -I{} rm -f {}; }
prune "$BACKUP_DIR/daily" "$KEEP_DAILY"
prune "$BACKUP_DIR/weekly" "$KEEP_WEEKLY"

# ── 4. Off-site ───────────────────────────────────────────────────────────────
STEP="off-site sync"
if [ $REMOTE = 1 ]; then
  if command -v rclone >/dev/null && rclone listremotes | grep -qx "$RCLONE_REMOTE"; then
    log "Syncing to $RCLONE_REMOTE ..."
    rclone sync "$BACKUP_DIR" "$RCLONE_REMOTE" --exclude 'backup.log' --transfers 8 --stats-one-line -q
    log "Off-site copy up to date."
  else
    log "No rclone remote '$RCLONE_REMOTE' — local backup only (run deploy/backup-setup.sh for off-site)."
  fi
fi
log "Done."
