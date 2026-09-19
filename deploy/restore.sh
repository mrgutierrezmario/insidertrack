#!/bin/bash
# Restore the InsiderTrack stack from a backup made by deploy/backup.sh.
#
#   deploy/restore.sh latest                       newest local daily bundle
#   deploy/restore.sh daily/stock-tracker-2026-09-19.tar.gz
#   deploy/restore.sh --from-remote latest         fetch the off-site copy first
#                                                  (new machine)
#
# On a blank machine: install Docker (and rclone if the backup is off-site),
# clone the repository, run deploy/restore.sh --from-remote latest. It
# recreates deploy/.env, the database (which holds the API keys and settings
# too) and the Tailscale identity (same URL), then starts the stack.
#
# On a running stack it REPLACES the database with the backup — everything
# ingested since the backup is lost until the next sync/backfill. It asks first.
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"
PROJECT=stock-tracker
PGUSER_=stockuser; PGDB_=stocktracker
BACKUP_DIR="${BACKUP_DIR:-$PWD/state/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-stock-tracker-backup:}"

FROM_REMOTE=0; TARGET=""
for arg in "$@"; do
  case "$arg" in
    --from-remote) FROM_REMOTE=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) TARGET="$arg" ;;
  esac
done
[ -n "$TARGET" ] || { sed -n '2,15p' "$0"; exit 1; }
log() { echo "[restore] $*"; }

if [ $FROM_REMOTE = 1 ]; then
  command -v rclone >/dev/null || { echo "rclone is needed for --from-remote (brew install rclone)." >&2; exit 1; }
  rclone listremotes | grep -qx "$RCLONE_REMOTE" || { echo "No rclone remote '$RCLONE_REMOTE' — run deploy/backup-setup.sh first." >&2; exit 1; }
  log "Downloading backups from $RCLONE_REMOTE ..."
  mkdir -p "$BACKUP_DIR"
  rclone copy "$RCLONE_REMOTE" "$BACKUP_DIR" --transfers 8 --stats-one-line -q
fi

if [ "$TARGET" = latest ]; then
  BUNDLE=$(ls -1t "$BACKUP_DIR"/daily/$PROJECT-*.tar.gz 2>/dev/null | head -1)
  [ -n "$BUNDLE" ] || { echo "No bundles in $BACKUP_DIR/daily" >&2; exit 1; }
else
  BUNDLE="$TARGET"; [ -f "$BUNDLE" ] || BUNDLE="$BACKUP_DIR/$TARGET"
  [ -f "$BUNDLE" ] || { echo "Bundle not found: $TARGET" >&2; exit 1; }
fi
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
tar -C "$WORK" -xzf "$BUNDLE"
STAGE=$(ls -d "$WORK"/$PROJECT-*)
log "Restoring from $(basename "$BUNDLE") (made $(basename "$STAGE" | sed "s/$PROJECT-//"))"

if [ ! -f .env ]; then
  cp "$STAGE/env" .env; log "Recreated deploy/.env from the backup."
elif ! cmp -s "$STAGE/env" .env; then
  log "NOTE: deploy/.env differs from the backup's copy; keeping the current one."
  log "      (DB_PASSWORD must match the one Postgres was created with.)"
fi

if docker volume inspect "${PROJECT}_postgres-data" >/dev/null 2>&1; then
  echo
  echo "  This REPLACES the current database with the backup."
  echo "  Everything ingested since then is gone until the next sync/backfill."
  read -r -p "  Type 'restore' to continue: " answer
  [ "$answer" = restore ] || { echo "Cancelled."; exit 1; }
fi

log "Starting postgres and tailscale (app stays down while restoring)..."
$DC stop app >/dev/null 2>&1 || true
$DC up -d postgres tailscale-config tailscale
for i in $(seq 1 60); do $DC exec -T postgres pg_isready -q -U "$PGUSER_" -d postgres && break; sleep 1; done

log "Restoring the database..."
$DC exec -T postgres psql -U "$PGUSER_" -d postgres -q -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS $PGDB_ WITH (FORCE);" -c "CREATE DATABASE $PGDB_;"
gzip -dc "$STAGE/db.sql.gz" | $DC exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -q -v ON_ERROR_STOP=1 -o /dev/null
log "  $($DC exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -tAc \
  "select count(*) || ' trades, ' || (select count(*) from politicians) || ' members, ' || (select count(*) from form4_transactions) || ' Form 4 rows' from trades")"

if [ -z "$($DC exec -T tailscale ls /var/lib/tailscale 2>/dev/null | grep -v '^$' || true)" ]; then
  log "Restoring the Tailscale identity (same URL as before)..."
  $DC stop tailscale >/dev/null
  docker run --rm -i -v "${PROJECT}_tailscale-state:/v" busybox:stable sh -c 'rm -rf /v/* /v/.[!.]* 2>/dev/null; tar -C /v -xzf -' < "$STAGE/tailscale-state.tar.gz"
else
  log "Tailscale is already signed in on this machine; keeping its identity."
fi

log "Starting the stack..."
./start.sh
