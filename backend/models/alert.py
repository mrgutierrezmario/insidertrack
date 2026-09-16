from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class AlertRule(Base):
    """A user-defined condition that, when met, produces an AlertEvent."""
    __tablename__ = "alert_rules"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(120), nullable=False)
    alert_type  = Column(String(40), nullable=False)
    # alert_type ∈ high_signal | momentum | insider_buy | whale_new | earnings_soon
    ticker      = Column(String(20), nullable=True)   # blank = any ticker
    threshold   = Column(Float, nullable=True)        # score / days / $ — meaning depends on type
    is_active   = Column(Boolean, default=True)
    notify_email = Column(String(255), nullable=True) # optional — email when triggered
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    events = relationship("AlertEvent", back_populates="rule", cascade="all, delete-orphan")


class AlertEvent(Base):
    """A single firing of an AlertRule."""
    __tablename__ = "alert_events"

    id          = Column(Integer, primary_key=True, index=True)
    rule_id     = Column(Integer, ForeignKey("alert_rules.id"), nullable=False)
    ticker      = Column(String(20), index=True)
    message     = Column(Text, nullable=False)
    dedup_key   = Column(String(200), unique=True, index=True)
    seen        = Column(Boolean, default=False)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())

    rule = relationship("AlertRule", back_populates="events")
