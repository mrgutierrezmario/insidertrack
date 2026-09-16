#!/bin/bash
# Wait for Postgres, then serve. Schema is created/migrated by init_db() on startup.
set -e

host="${POSTGRES_HOST:-postgres}"
echo "[app] waiting for postgres at $host..."
for i in $(seq 1 60); do
  pg_isready -q -h "$host" -p 5432 && break
  sleep 1
done

echo "[app] starting on :8003"
# --forwarded-allow-ips="" keeps uvicorn from rewriting client addresses;
# routers/access.py:_get_ip() handles X-Forwarded-For via TRUSTED_PROXIES.
uvicorn main:app --host 0.0.0.0 --port 8003 --forwarded-allow-ips="" &
pid=$!
trap 'kill -TERM $pid 2>/dev/null; wait $pid' TERM INT

# Watchdog: this container shares the tailscale container's network namespace.
# If tailscale restarts, that namespace is gone and "$host" stops resolving; the
# only way back is to restart this container (restart: unless-stopped), which
# joins the new namespace.
fails=0
while kill -0 "$pid" 2>/dev/null; do
  sleep 15
  if getent hosts "$host" >/dev/null 2>&1; then
    fails=0
  else
    fails=$((fails + 1))
    if [ "$fails" -ge 3 ]; then
      echo "[app] cannot resolve $host for 45 s — network namespace lost, exiting so Docker restarts us"
      # Graceful stop can hang on connections that will never come back; force it.
      kill -TERM "$pid" 2>/dev/null
      for i in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -KILL "$pid" 2>/dev/null; wait "$pid" || true
      exit 1
    fi
  fi
done
wait "$pid"
