from sqlalchemy import Column, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class ModelBrief(Base):
    """One per day: the model's short read of that morning's disclosures."""
    __tablename__ = "model_briefs"

    brief_date   = Column(Date, primary_key=True)
    summary      = Column(Text, nullable=False)
    provider     = Column(String(60))           # e.g. "gemini/gemini-flash-latest"
    context_json = Column(Text)                 # what the model was shown (for audit)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class ModelCall(Base):
    """A single directional call the model made, held to the same standard as
    the members: measured at its horizon against SPY, and never edited."""
    __tablename__ = "model_calls"
    __table_args__ = (UniqueConstraint("call_date", "ticker", name="uq_model_call_day_ticker"),)

    id            = Column(Integer, primary_key=True)
    call_date     = Column(Date, index=True, nullable=False)
    ticker        = Column(String(20), index=True, nullable=False)
    direction     = Column(String(8), nullable=False)      # bullish | bearish
    horizon_days  = Column(Integer, nullable=False)        # 30 | 60 | 90
    confidence    = Column(Float)                          # 0–1, the model's own
    reasoning     = Column(Text)
    provider      = Column(String(60))
    price_at_call = Column(Float)
    # Filled once call_date + horizon has passed
    price_at_horizon = Column(Float)
    return_pct    = Column(Float)
    spy_return_pct = Column(Float)
    excess_pct    = Column(Float)
    outcome       = Column(String(4))                      # hit | miss
    resolved_at   = Column(DateTime(timezone=True))
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
