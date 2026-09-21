#!/bin/bash

# InsiderTrack startup script
# Run from the stock-tracker/ directory: bash start.sh
# Development only (hot code, local Postgres). Production: deploy/start.sh

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/app/ui_backend"
FRONTEND_DIR="$ROOT_DIR/app/ui_frontend"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

info()    { echo -e "${CYAN}[INFO]${RESET}  $1"; }
success() { echo -e "${GREEN}[OK]${RESET}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $1"; }
error()   { echo -e "${RED}[ERROR]${RESET} $1"; exit 1; }

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PIDS=()
cleanup() {
  echo ""
  info "Shutting down..."
  for pid in "${PIDS[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  # Watchdog: if any child ignores SIGTERM, SIGKILL it after 5s so `wait` below
  # can't hang forever.
  ( sleep 5; for pid in "${PIDS[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done ) &
  WATCHDOG_PID=$!
  # Reap children so they don't become <defunct> zombies inherited by init.
  # `wait` blocks until each child exits AND collects its exit status.
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  # Reap the watchdog too (kill it early if children exited before the 5s mark).
  kill -TERM "$WATCHDOG_PID" 2>/dev/null || true
  wait "$WATCHDOG_PID" 2>/dev/null || true
  # Only stop Docker DB if we started it
  if [ "${STARTED_DOCKER_DB:-0}" = "1" ]; then
    info "Stopping Docker database..."
    compose stop db 2>/dev/null || true
  fi
  success "All services stopped."
}
trap cleanup EXIT INT TERM

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ██████ InsiderTrack${RESET}"
echo -e "  Congressional & Whale Stock Tracker"
echo ""

# ── Prerequisite checks ───────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || error "Python 3 not found."
command -v node    >/dev/null 2>&1 || error "Node.js not found."
command -v npm     >/dev/null 2>&1 || error "npm not found."
success "Core prerequisites found."

# `docker compose` (v2 plugin) is what Docker ships today; `docker-compose`
# (v1 binary) still exists on older installs. One wrapper, either works.
COMPOSE=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
fi
compose() { $COMPOSE -f "$ROOT_DIR/docker-compose.yml" --env-file "$BACKEND_DIR/.env" "$@"; }

# Where the app reaches the Docker DB. Override DEV_DB_PORT if 5433 is taken;
# DEV_DB_HOST only matters inside a devcontainer that shares the host's Docker.
export DEV_DB_PORT="${DEV_DB_PORT:-5433}"
DEV_DB_HOST="${DEV_DB_HOST:-localhost}"

# ── .env check ────────────────────────────────────────────────────────────────
if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  warn "app/ui_backend/.env not found — created it from .env.example with defaults. Edit it to add API keys."
fi

# Postgres credentials the DB checks below must match what the app will use.
# .env.example ships defaults, so these are always set after the copy above.
PG_USER="$(grep -E '^POSTGRES_USER=' "$BACKEND_DIR/.env" | cut -d= -f2-)"
PG_DB="$(grep -E '^POSTGRES_DB=' "$BACKEND_DIR/.env" | cut -d= -f2-)"
PG_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' "$BACKEND_DIR/.env" | cut -d= -f2-)"
PG_USER="${PG_USER:-stockuser}"; PG_DB="${PG_DB:-stocktracker}"; PG_PASSWORD="${PG_PASSWORD:-stockpass}"

# Warn about optional keys
if ! grep -q "ALPHA_VANTAGE_KEY=." "$BACKEND_DIR/.env" 2>/dev/null; then
  warn "ALPHA_VANTAGE_KEY not set — intraday charts will be disabled."
fi
if ! grep -q "MAIL_PASSWORD=." "$BACKEND_DIR/.env" 2>/dev/null; then
  warn "MAIL_PASSWORD not set — email reports will be disabled."
fi

# ── Step 1: Python dependencies ───────────────────────────────────────────────
# A project-local venv (gitignored) keeps the app's pins off the system Python.
VENV="$BACKEND_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  info "Creating Python virtualenv (first run)..."
  python3 -m venv "$VENV" || error "Could not create a virtualenv. On Debian/Ubuntu: sudo apt install python3-venv"
fi
info "Installing Python dependencies..."
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$BACKEND_DIR/requirements.txt" \
  || error "pip install failed. Check the output above."
success "Python packages installed."

# ── Step 2: PostgreSQL ────────────────────────────────────────────────────────
# Try the DATABASE_URL from .env first (a local PostgreSQL, usually 5432), fall
# back to the Docker DB on $DEV_DB_PORT. The check is a real login, not
# pg_isready: another project's Postgres on 5432 (different user/database)
# answers pg_isready fine but rejects this app, which must fall through to
# its own container instead of failing at startup.
DB_READY=0
ENV_DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND_DIR/.env" | cut -d= -f2-)"

db_reachable() {  # $1 = URL; 3 s timeout so an unreachable host doesn't hang
  "$VENV/bin/python" - "$1" <<'PY' >/dev/null 2>&1
import sys, psycopg2
psycopg2.connect(sys.argv[1], connect_timeout=3).close()
PY
}

info "Checking for a local PostgreSQL..."
if [ -n "$ENV_DB_URL" ] && db_reachable "$ENV_DB_URL"; then
  success "PostgreSQL from .env accepts this app's credentials."
  DB_READY=1
fi

if [ "$DB_READY" = "0" ]; then
  if [ -n "$COMPOSE" ]; then
    info "Starting PostgreSQL via Docker (port $DEV_DB_PORT)..."
    compose up -d db || error "Could not start the Docker database. If the port is taken, re-run with DEV_DB_PORT=<free port> bash start.sh"
    STARTED_DOCKER_DB=1
    # Environment beats .env in pydantic-settings, so this steers the app at
    # the container without editing the user's file.
    export DATABASE_URL="postgresql://${PG_USER}:${PG_PASSWORD}@${DEV_DB_HOST}:${DEV_DB_PORT}/${PG_DB}"
    info "Waiting for PostgreSQL to be ready..."
    RETRIES=30
    until db_reachable "$DATABASE_URL"; do
      RETRIES=$((RETRIES - 1))
      [ "$RETRIES" -eq 0 ] && error "PostgreSQL did not start. Check: $COMPOSE -f docker-compose.yml logs db"
      sleep 1
    done
    success "Docker PostgreSQL is ready."
    DB_READY=1
  fi
fi

[ "$DB_READY" = "0" ] && error "No PostgreSQL accepts DATABASE_URL from app/ui_backend/.env, and Docker (with the compose plugin) is not available to start one."

# ── Step 3: Node dependencies ─────────────────────────────────────────────────
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  info "Installing Node packages (first run — this takes a minute)..."
  npm install --prefix "$FRONTEND_DIR" --silent
  success "Node packages installed."
else
  success "Node packages already installed."
fi

# ── Step 4: Build frontend (skip if dist is newer than src) ───────────────────
DIST_INDEX="$FRONTEND_DIR/dist/index.html"
NEEDS_BUILD=1
if [ -f "$DIST_INDEX" ] && [ -z "$(find "$FRONTEND_DIR/src" "$FRONTEND_DIR/package.json" "$FRONTEND_DIR/vite.config.js" -newer "$DIST_INDEX" 2>/dev/null | head -1)" ]; then
  NEEDS_BUILD=0
fi
if [ "$NEEDS_BUILD" = "1" ]; then
  info "Building frontend..."
  npm install --prefix "$FRONTEND_DIR" --silent
  npm run build --prefix "$FRONTEND_DIR" > "$LOG_DIR/frontend-build.log" 2>&1
  success "Frontend built."
else
  success "Frontend dist is up to date — skipping build."
fi

# ── Step 5: Start backend ─────────────────────────────────────────────────────
info "Starting app on port 8003..."
cd "$BACKEND_DIR"
# --forwarded-allow-ips="" disables uvicorn's built-in proxy-headers rewrite so
# routers/access.py:_get_ip() is the single source of truth (controlled by
# TRUSTED_PROXIES env var). Without this flag, uvicorn trusts X-Forwarded-For
# from 127.0.0.1 by default and clients can spoof their IP via the header.
"$VENV/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8003 --forwarded-allow-ips="" > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

# First boot creates the schema and runs migrations, which takes a moment.
RETRIES=60
until curl -sf http://localhost:8003/health >/dev/null 2>&1; do
  RETRIES=$((RETRIES - 1))
  [ "$RETRIES" -eq 0 ] && error "App did not start. Check logs/backend.log"
  sleep 1
done
success "App is running →  http://localhost:8003"
success "API docs       →  http://localhost:8003/docs"

# ── Ready ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  All services are up.${RESET}"
echo ""
echo -e "  ${CYAN}App${RESET}        http://localhost:8003"
echo -e "  ${CYAN}API Docs${RESET}   http://localhost:8003/docs"
echo -e "  ${CYAN}Public${RESET}     (dev only — the public URL is served by the deploy/ stack, see deploy/start.sh)"
echo ""
echo -e "  ${YELLOW}Logs:${RESET} logs/backend.log"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${RESET} to stop everything."
echo ""

wait "${BACKEND_PID}"
