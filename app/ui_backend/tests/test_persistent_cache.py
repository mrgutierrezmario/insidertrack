"""
Tests for the L2 persistent cache and its integration with the L1 in-memory
caches in services/market_data.py.

These run against the dev Postgres (the only place JSONB / ON CONFLICT work).
All keys are namespaced with a unique prefix so the tests don't collide with
real cached data, and the teardown sweeps them.
"""

import time
import uuid
import pytest

from services import persistent_cache as pc
from services import market_data as md


@pytest.fixture
def key_prefix():
    """Per-test unique key prefix + cleanup of any rows we wrote."""
    prefix = f"test_pc_{uuid.uuid4().hex[:8]}"
    yield prefix
    # Cleanup — every test key starts with the prefix
    from database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Cover both bare and hist:-prefixed keys (the history cache namespaces L2 keys)
        db.execute(
            text("DELETE FROM market_cache WHERE cache_key LIKE :p OR cache_key LIKE :h"),
            {"p": f"{prefix}%", "h": f"hist:{prefix}%"},
        )
        db.commit()
    finally:
        db.close()
    # Also clear any L1 entries that might leak between tests
    for k in [k for k in md._cache if k.startswith(prefix)]:
        del md._cache[k]
    for k in [k for k in md._history_cache if k.startswith(f"hist:{prefix}") or k.startswith(prefix)]:
        del md._history_cache[k]


# ── persistent_cache module ──────────────────────────────────────────────────

class TestPersistentCacheRoundtrip:
    def test_set_then_get(self, key_prefix):
        pc.cache_set(f"{key_prefix}:k1", {"hello": "world"}, ttl_seconds=60)
        result = pc.cache_get(f"{key_prefix}:k1")
        assert result is not None
        value, remaining = result
        assert value == {"hello": "world"}
        assert 0 < remaining <= 60

    def test_get_missing_key_returns_none(self, key_prefix):
        assert pc.cache_get(f"{key_prefix}:never-set") is None

    def test_set_is_upsert(self, key_prefix):
        pc.cache_set(f"{key_prefix}:k", "first", ttl_seconds=60)
        pc.cache_set(f"{key_prefix}:k", "second", ttl_seconds=60)
        value, _ = pc.cache_get(f"{key_prefix}:k")
        assert value == "second"

    def test_non_json_serializable_is_swallowed(self, key_prefix):
        # A set() can't be JSON-encoded — cache_set should silently skip, not raise
        pc.cache_set(f"{key_prefix}:bad", {1, 2, 3}, ttl_seconds=60)
        assert pc.cache_get(f"{key_prefix}:bad") is None

    def test_delete_expired_removes_only_expired_rows(self, key_prefix):
        # Two rows: one fresh, one already-expired
        pc.cache_set(f"{key_prefix}:fresh", "stay", ttl_seconds=300)
        # Cheat: insert an already-expired row directly
        from database import SessionLocal
        from models.market_cache import MarketCacheEntry
        from datetime import datetime, timedelta, timezone
        db = SessionLocal()
        try:
            db.add(MarketCacheEntry(
                cache_key=f"{key_prefix}:old",
                value="gone",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ))
            db.commit()
        finally:
            db.close()
        # Sweep
        deleted = pc.cache_delete_expired()
        assert deleted >= 1  # at least our expired row (other tests may add more)
        # Fresh row survives
        assert pc.cache_get(f"{key_prefix}:fresh") is not None
        # Expired row is gone
        assert pc.cache_get(f"{key_prefix}:old") is None


# ── L1 + L2 integration ──────────────────────────────────────────────────────

class TestL1L2Integration:
    def test_l1_set_writes_through_to_l2(self, key_prefix):
        """_cache_set populates both layers — verify L2 by checking pc.cache_get directly."""
        md._cache_set(f"{key_prefix}:wt", {"x": 1}, ttl=60)
        l2 = pc.cache_get(f"{key_prefix}:wt")
        assert l2 is not None
        value, _ = l2
        assert value == {"x": 1}

    def test_l2_hydrates_l1_after_restart_simulation(self, key_prefix):
        """The whole point of L2: warm cache survives an L1 wipe."""
        key = f"{key_prefix}:warm"
        md._cache_set(key, {"price": 100}, ttl=60)
        assert md._cache_get(key) == {"price": 100}

        # Simulate restart: clear L1
        if key in md._cache:
            del md._cache[key]

        # L1 is empty but L2 has it — _cache_get should hydrate L1 and return
        result = md._cache_get(key)
        assert result == {"price": 100}
        # L1 is now populated again with a fresh entry
        assert key in md._cache

    def test_l1_hit_does_not_touch_l2(self, key_prefix, monkeypatch):
        """Hot path: when L1 is fresh, we shouldn't even consult L2."""
        key = f"{key_prefix}:hot"
        md._cache_set(key, "v", ttl=60)
        # If pc.cache_get is called we want to know — monkeypatch to raise
        calls = []
        original = pc.cache_get
        def spy(k):
            calls.append(k)
            return original(k)
        monkeypatch.setattr(pc, "cache_get", spy)
        # Also patch the reference seen by market_data after its lazy import
        import services.persistent_cache as pc_mod
        monkeypatch.setattr(pc_mod, "cache_get", spy)

        # First call — L1 hit, L2 should NOT be consulted
        md._cache_get(key)
        assert key not in calls

    def test_history_l2_hydration(self, key_prefix):
        """Same warm-loading pattern for the long-TTL history cache."""
        key = f"{key_prefix}:hist1"
        bars = [{"date": "2026-05-26", "close": 100.0}]
        md._history_cache_set(key, bars)
        assert md._history_cache_get(key) == bars

        # Simulate restart
        if key in md._history_cache:
            del md._history_cache[key]

        result = md._history_cache_get(key)
        assert result == bars
        assert key in md._history_cache
