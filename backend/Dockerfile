# Multi-stage build. Build context must be the project root (see docker-compose.yml)
# so this Dockerfile can see both backend/ and frontend/.

# Stage 1 — build the React frontend
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2 — Python runtime
FROM python:3.11-slim
WORKDIR /app

# postgresql-client supplies `pg_dump` used by services/db_backup.py.
# rm -rf the apt lists after install to keep the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# main.py:41 resolves Path(__file__).parent.parent / "frontend" / "dist".
# With main.py at /app/main.py, that lands at /frontend/dist.
COPY --from=frontend-builder /build/dist /frontend/dist

EXPOSE 8003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003", "--forwarded-allow-ips="]
