from sqlalchemy import Column, DateTime, JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from database import Base


# Use the Postgres-native JSONB in prod (binary storage, faster, indexable),
# fall through to the cross-platform JSON in test envs (SQLite). Same Python-side
# API; the column-type swap is transparent to callers.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


class MarketCacheEntry(Base):
    """
    Persistent L2 cache for market_data — survives process restart.

    L1 (in-memory dict in services/market_data.py) handles the hot path.
    On L1 miss, L2 is consulted; on L2 hit, L1 is hydrated with the
    remaining TTL. On write, both are populated. Expired entries are
    swept by a scheduler job.
    """
    __tablename__ = "market_cache"

    cache_key  = Column(Text, primary_key=True)
    value      = Column(JsonColumn, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
