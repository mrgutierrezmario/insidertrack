# Production image: React UI built and served by the FastAPI backend on :8003.
# Build context is the repository root (see deploy/compose.yml).

# ── Stage 1: build the UI ─────────────────────────────────────────────────────
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── Stage 2: backend ──────────────────────────────────────────────────────────
FROM python:3.11-slim

# postgresql-client: pg_dump for services/db_backup.py + pg_isready for the
# startup wait. curl: healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# main.py resolves Path(__file__).parent.parent / "frontend" / "dist".
# With main.py at /app/main.py, that lands at /frontend/dist.
COPY --from=ui /ui/dist /frontend/dist
COPY deploy/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fs http://localhost:8003/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
