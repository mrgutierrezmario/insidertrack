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
    docker-compose -f "$ROOT_DIR/docker-compose.yml" stop db 2>/dev/null || true
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

# ── .env check ────────────────────────────────────────────────────────────────
if [ ! -f "$BACKEND_DIR/.env" ]; then
  error "app/ui_backend/.env not found. Copy app/ui_backend/.env.example to app/ui_backend/.env and fill in your credentials."
fi

# Warn about optional keys
if ! grep -q "ALPHA_VANTAGE_KEY=." "$BACKEND_DIR/.env" 2>/dev/null; then
  warn "ALPHA_VANTAGE_KEY not set — intraday charts will be disabled."
fi
if ! grep -q "MAIL_PASSWORD=." "$BACKEND_DIR/.env" 2>/dev/null; then
  warn "MAIL_PASSWORD not set — email reports will be disabled."
fi

# ── Step 1: PostgreSQL ────────────────────────────────────────────────────────
# Try local PostgreSQL first (port 5432), fall back to Docker (port 5433)
DB_READY=0

info "Checking for local PostgreSQL..."
if command -v pg_isready >/dev/null 2>&1 && pg_isready -h localhost -p 5432 -U stockuser -d stocktracker >/dev/null 2>&1; then
  success "Local PostgreSQL is ready (port 5432)."
  DB_READY=1
fi

if [ "$DB_READY" = "0" ]; then
  if command -v docker >/dev/null 2>&1 && command -v docker-compose >/dev/null 2>&1; then
    info "Starting PostgreSQL via Docker (port 5433)..."
    docker-compose -f "$ROOT_DIR/docker-compose.yml" up -d db
    STARTED_DOCKER_DB=1
    info "Waiting for PostgreSQL to be ready..."
    RETRIES=20
    until docker-compose -f "$ROOT_DIR/docker-compose.yml" exec -T db \
      pg_isready -U stockuser -d stocktracker >/dev/null 2>&1; do
      RETRIES=$((RETRIES - 1))
      [ "$RETRIES" -eq 0 ] && error "PostgreSQL did not start. Check: docker-compose logs db"
      sleep 1
    done
    success "Docker PostgreSQL is ready."
    DB_READY=1
  fi
fi

[ "$DB_READY" = "0" ] && error "No PostgreSQL found. Install PostgreSQL locally or install Docker."

# ── Step 2: Python dependencies ───────────────────────────────────────────────
info "Installing Python dependencies..."
pip install -q -r "$BACKEND_DIR/requirements.txt" --break-system-packages 2>/dev/null \
  || pip install -q -r "$BACKEND_DIR/requirements.txt"
success "Python packages installed."

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
python3 -m uvicorn main:app --host 0.0.0.0 --port 8003 --forwarded-allow-ips="" > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

RETRIES=20
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
