from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Float, Date, DateTime
from sqlalchemy.sql import func
from database import Base


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    id               = Column(Integer, primary_key=True, index=True)
    ticker           = Column(String(20), index=True, nullable=False)
    signal_date      = Column(Date, index=True, nullable=False)

    # Signal state at snapshot time
    composite_score  = Column(Integer)
    label            = Column(String(50))
    signal           = Column(String(20))   # BULLISH / NEUTRAL / BEARISH
    price_at_signal  = Column(Float)

    # Politician whose trade most recently drove the signal (captured at snapshot time).
    # FK + ON DELETE SET NULL — losing a politician shouldn't cascade-delete history.
    politician_id    = Column(Integer, ForeignKey("politicians.id", ondelete="SET NULL"), nullable=True, index=True)
    politician_name  = Column(String(200), nullable=True)

    # Sub-scores
    smart_money_score = Column(Integer)
    insider_score     = Column(Integer)   # congressional
    corporate_score   = Column(Integer)   # Form 4 (added 2026-09; NULL on older rows)
    # Which scoring regime produced composite_score (routers.signals.SCORE_VERSION).
    # Hit-rates are only comparable within one version.
    score_version     = Column(Integer)
    momentum_score    = Column(Integer)
    sentiment_score   = Column(Integer)
    risk_penalty      = Column(Integer)

    # Filled in by the daily fill job
    price_30d    = Column(Float,   nullable=True)
    price_60d    = Column(Float,   nullable=True)
    price_90d    = Column(Float,   nullable=True)
    return_30d   = Column(Float,   nullable=True)   # percentage, e.g. 4.2 = +4.2%
    return_60d   = Column(Float,   nullable=True)
    return_90d   = Column(Float,   nullable=True)
    outcome_30d  = Column(String(8), nullable=True)  # UP / DOWN / FLAT
    outcome_60d  = Column(String(8), nullable=True)
    outcome_90d  = Column(String(8), nullable=True)

    # True when this row was reconstructed by the gap-backfill job rather than
    # snapshotted live. Backfilled rows have approximate sentiment (Alpha Vantage
    # news isn't historical) — the UI can flag them so win-rate stats stay honest.
    is_backfilled = Column(Boolean, default=False, nullable=False, server_default="false")

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
