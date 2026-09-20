#!/bin/bash
# Start (or update) the whole InsiderTrack stack in its own containers.
# Safe to re-run: rebuilds the app image if code changed, restarts what needs it,
# leaves data alone. Run it again after pulling new code.
#
#   deploy/start.sh            build + start everything, print the public URL
#   deploy/stop.sh             stop (data is kept in Docker volumes)
#   docker compose -f deploy/compose.yml logs -f app     follow the app log
#
# First run: if the database is empty and deploy/state/ holds a *.dump
# (pg_dump custom format), the newest one is restored before the app starts.
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose -f compose.yml"

log() { echo "[start] $*"; }
# Load deploy/.env without `source` (values may contain spaces, e.g. MAIL_FROM_NAME).
load_env() {
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key=${line%%=*}; val=${line#*=}
    case "$val" in \"*\") val=${val#\"}; val=${val%\"} ;; \'*\') val=${val#\'}; val=${val%\'} ;; esac
    export "$key=$val"
  done < "$1"
}
gen() { python3 -c "import secrets; print(secrets.token_urlsafe(${1:-24}))"; }

command -v docker >/dev/null || { echo "Docker is not installed or not on PATH." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running — start Docker Desktop first." >&2; exit 1; }

# ── First run: create deploy/.env with generated secrets ──────────────────────
if [ ! -f .env ]; then
  log "Creating deploy/.env with generated secrets..."
  cp .env.example .env
  sed -i.bak "s|^DB_PASSWORD=$|DB_PASSWORD=$(gen)|; s|^ADMIN_PASSWORD=$|ADMIN_PASSWORD=$(gen 12)|" .env
  rm -f .env.bak
  echo "  ^ ADMIN_PASSWORD was generated — see deploy/.env"
fi
load_env .env
PGUSER_=stockuser; PGDB_=stocktracker   # fixed in compose.yml

# ── Database first (so a first-run restore happens before the app starts) ─────
log "Starting database..."
$DC up -d postgres
for i in $(seq 1 60); do
  $DC exec -T postgres pg_isready -q -U "$PGUSER_" -d "$PGDB_" 2>/dev/null && break
  sleep 1
done
$DC exec -T postgres pg_isready -q -U "$PGUSER_" -d "$PGDB_" || { echo "Database did not start. Logs:" >&2; $DC logs --tail=40 postgres >&2; exit 1; }

tables=$($DC exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '[:space:]' || echo 0)
if [ "${tables:-0}" = "0" ]; then
  dump=$(ls -1t state/*.dump 2>/dev/null | head -1 || true)
  if [ -n "$dump" ]; then
    log "Database is empty — restoring $(basename "$dump")..."
    $DC exec -T postgres pg_restore -U "$PGUSER_" -d "$PGDB_" --no-owner --no-privileges < "$dump" \
      || { echo "pg_restore failed." >&2; exit 1; }
    log "Restored $($DC exec -T postgres psql -U "$PGUSER_" -d "$PGDB_" -tAc "SELECT count(*) FROM trades;" | tr -d '[:space:]') trades."
  else
    log "Database is empty and deploy/state/ has no dump — starting fresh."
  fi
else
  log "Database already has $tables tables — leaving it alone."
fi

# ── Don't restart the app under a running job ─────────────────────────────────
# A backfill, re-parse, congressional sync or skill refresh dies with the
# container. They're idempotent, but losing an hour of work by accident is
# silly. `deploy/start.sh --force` overrides.
if [ "${1:-}" != "--force" ] && $DC ps --status running --services 2>/dev/null | grep -qx app; then
  jobs=$($DC exec -T app curl -s --max-time 5 http://localhost:8003/jobs/running 2>/dev/null || true)
  if printf '%s' "$jobs" | grep -q '"any": *true'; then
    echo "A long job is running in the app; a restart would kill it:" >&2
    printf '%s\n' "$jobs" | sed 's/^/  /' >&2
    echo "Wait for it (Admin → Data sources shows progress), or run: deploy/start.sh --force" >&2
    exit 1
  fi
fi

# ── Build and start the rest ──────────────────────────────────────────────────
log "Building and starting containers (first build takes a few minutes)..."
$DC up -d --build --remove-orphans

# ── Tailscale: sign in once ───────────────────────────────────────────────────
# containerboot gives `tailscale up` 60 s to authenticate, then exits and the
# container restarts — which rotates the login link and detaches the app from
# the shared network namespace. So for the first sign-in we stop the tunnel and
# run `tailscale up` by hand against the same state volume: the link it prints
# stays valid until you open it. The login is persisted, so this only happens once.
ts() { $DC exec -T tailscale tailscale "$@"; }
for i in $(seq 1 15); do ts status >/dev/null 2>&1 && break; sleep 2; done
if ! ts status >/dev/null 2>&1; then
  log "Tailscale is not signed in yet — one-time interactive login."
  $DC stop app tailscale >/dev/null
  echo
  echo "============================================================"
  echo "  Open the link below on any device and sign in to your tailnet."
  echo "  (Tip: set TS_AUTHKEY in deploy/.env to skip this in future.)"
  echo "============================================================"
  $DC run --rm --no-deps -T tailscale sh -c '
    tailscaled --tun=userspace-networking --statedir=/var/lib/tailscale --socket=/tmp/tailscaled.sock >/dev/null 2>&1 &
    for i in $(seq 1 30); do [ -S /tmp/tailscaled.sock ] && break; sleep 1; done
    tailscale --socket=/tmp/tailscaled.sock up --hostname="$TS_HOSTNAME" --accept-dns=false' \
    || { echo "Sign-in did not complete — re-run deploy/start.sh to try again." >&2; exit 1; }
  log "Signed in. Starting the tunnel and the app..."
  $DC up -d
  for i in $(seq 1 30); do ts status >/dev/null 2>&1 && break; sleep 2; done
fi
ts status >/dev/null 2>&1 && log "Tailscale connected as $(ts status --self=true --peers=false 2>/dev/null | awk 'NR==1{print $2}')"

# ── App health ────────────────────────────────────────────────────────────────
log "Waiting for the app..."
for i in $(seq 1 90); do
  $DC exec -T app curl -fs http://localhost:8003/health >/dev/null 2>&1 && break
  sleep 2
done
$DC exec -T app curl -fs http://localhost:8003/health >/dev/null 2>&1 || {
  echo "App did not become healthy. Logs:" >&2; $DC logs --tail=40 app >&2; exit 1; }

# ── Done ──────────────────────────────────────────────────────────────────────
PUBLIC=$(ts funnel status 2>/dev/null | grep -oE 'https://[a-z0-9.-]+\.ts\.net' | head -1)
echo
echo "============================================================"
echo "  InsiderTrack is running."
echo "  Public URL:  ${PUBLIC:-(Funnel not active yet — run deploy/start.sh again in a minute)}"
echo "  Local URL:   http://localhost:${APP_PORT:-8013}"
echo "============================================================"
if [ -n "$PUBLIC" ] && [ "${PUBLIC#https://}" != "${PUBLIC_DOMAIN:-}" ]; then
  echo "  NOTE: PUBLIC_DOMAIN in deploy/.env is '${PUBLIC_DOMAIN:-}' but Funnel serves ${PUBLIC#https://}."
  echo "        Set PUBLIC_DOMAIN=${PUBLIC#https://} and re-run so CORS trusts the public origin."
fi
if [ -n "$PUBLIC" ] && ! ts funnel status 2>/dev/null | grep -q "Funnel on"; then
  echo "  Funnel is not enabled for your Tailscale account yet. Run:"
  echo "    docker compose -f deploy/compose.yml exec tailscale tailscale funnel --bg 8003"
  echo "  and open the link it prints, then re-run deploy/start.sh."
fi
