"""
Postgres-backed L2 cache for market_data.

The L1 (in-memory dict in services/market_data.py) handles the hot path —
reads on the same process tick are sub-microsecond. The L2 here adds
durability: after a restart the L1 is empty but the L2 still has whatever
was in flight, so the first request for any still-fresh ticker warm-loads
L1 instead of paying a fresh yfinance / Alpha Vantage round-trip.

JSON-serializable values only — the column is JSONB. Anything that doesn't
encode is logged and silently skipped (the caller still got their L1 write,
so behavior degrades to L1-only rather than crashing).
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from database import SessionLocal
from models.market_cache import MarketCacheEntry

logger = logging.getLogger(__name__)


def cache_get(key: str) -> tuple[object, int] | None:
    """
    Return ``(value, remaining_ttl_seconds)`` if ``key`` is cached and not
    expired, otherwise None. Caller passes ``remaining_ttl_seconds`` back
    to ``_cache_set`` to hydrate L1 with the correct TTL.
    """
    try:
        with SessionLocal() as db:
            row = db.query(MarketCacheEntry).filter(MarketCacheEntry.cache_key == key).first()
            if not row:
                return None
            now = datetime.now(timezone.utc)
            if row.expires_at <= now:
                return None
            remaining = max(1, int((row.expires_at - now).total_seconds()))
            return row.value, remaining
    except Exception:
        logger.exception("L2 cache_get failed for key=%s", key)
        return None


def cache_set(key: str, value: object, ttl_seconds: int) -> None:
    """UPSERT (key, value) with the given TTL. JSON-encode failure is swallowed."""
    try:
        # Pre-flight JSON encode so we fail loudly here instead of in the DB driver.
        json.dumps(value)
    except (TypeError, ValueError):
        logger.debug("L2 cache_set skipped (not JSON-serializable) for key=%s", key)
        return

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    try:
        with SessionLocal() as db:
            stmt = insert(MarketCacheEntry).values(
                cache_key=key, value=value, expires_at=expires_at,
            ).on_conflict_do_update(
                index_elements=["cache_key"],
                set_={"value": value, "expires_at": expires_at},
            )
            db.execute(stmt)
            db.commit()
    except Exception:
        logger.exception("L2 cache_set failed for key=%s", key)


def cache_delete_expired() -> int:
    """Delete every row whose expires_at is in the past. Returns the count."""
    try:
        with SessionLocal() as db:
            result = db.execute(
                text("DELETE FROM market_cache WHERE expires_at < NOW()")
            )
            db.commit()
            return result.rowcount or 0
    except Exception:
        logger.exception("L2 cache_delete_expired failed")
        return 0
