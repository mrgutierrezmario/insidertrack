"""
Daily Postgres backup. `pg_dump` runs against the configured DATABASE_URL,
writes a date-stamped custom-format `.dump` file to BACKUP_DIR, and prunes
older files past KEEP_LATEST.

Restore (one-off, manual):
    pg_restore -U stockuser -d stocktracker --clean --if-exists \
        --no-owner --no-privileges  <  insidertrack-YYYY-MM-DD.dump

Requires the `pg_dump` binary in PATH. In dev the system package supplies it;
in the Dockerfile we install `postgresql-client` alongside the Python runtime.
"""

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

# Bind-mount this in docker-compose so backups survive container recreation.
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/workspaces/projects/stock-tracker/logs/backups"))
KEEP_LATEST = 7  # one week of dailies — adjust if you run more aggressive retention


def run_backup() -> Path | None:
    """
    Run pg_dump and return the file path on success, None on failure.
    Output: `<BACKUP_DIR>/insidertrack-YYYY-MM-DD.dump` (custom format).
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"insidertrack-{datetime.utcnow().strftime('%Y-%m-%d')}.dump"

    try:
        # pg_dump reads connection params from libpq URL form via -d.
        # --no-owner / --no-privileges keep the dump portable across DB users.
        result = subprocess.run(
            [
                "pg_dump",
                "-d", settings.database_url,
                "-F", "c",
                "--no-owner",
                "--no-privileges",
                "-f", str(target),
            ],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            logger.error("pg_dump failed (exit=%d): %s", result.returncode, result.stderr.strip())
            # Clean up partial file so the next run sees a clean slate
            target.unlink(missing_ok=True)
            return None
        size_kb = target.stat().st_size // 1024
        logger.info("DB backup OK: %s (%d KB)", target.name, size_kb)
        return target
    except FileNotFoundError:
        logger.error("pg_dump binary not found in PATH — install postgresql-client")
        return None
    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out after 600s")
        target.unlink(missing_ok=True)
        return None
    except Exception:
        logger.exception("pg_dump unexpected failure")
        return None


def prune_old(keep: int = KEEP_LATEST) -> int:
    """Delete all but the `keep` most recent insidertrack-*.dump files. Returns count deleted."""
    try:
        files = sorted(
            BACKUP_DIR.glob("insidertrack-*.dump"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        deleted = 0
        for old in files[keep:]:
            old.unlink(missing_ok=True)
            deleted += 1
        if deleted:
            logger.info("DB backup prune: removed %d old file(s)", deleted)
        return deleted
    except Exception:
        logger.exception("DB backup prune failed")
        return 0
