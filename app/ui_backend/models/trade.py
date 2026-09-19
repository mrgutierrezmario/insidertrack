from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    politician_id = Column(Integer, ForeignKey("politicians.id"), nullable=False)
    ticker = Column(String, index=True)
    asset_name = Column(String)
    transaction_type = Column(String)  # purchase | sale | sale_partial | exchange
    amount_range = Column(String)      # e.g. "$1,001 - $15,000"
    # Parsed bounds of amount_range (dollars). high is NULL for open-ended
    # brackets ("Over $50,000,000"). Lets the score weight by size, not count.
    amount_low = Column(Integer)
    amount_high = Column(Integer)
    # self | spouse | child | joint — STOCK Act filings distinguish these.
    owner = Column(String(8))
    # stock | option | other. Options are stored under their underlying ticker,
    # so this is what stops a put purchase from reading as a stock buy.
    asset_type = Column(String(8), index=True)
    # buy | sell | NULL — the trade's bet on the ticker, computed once at ingest
    # by services.trade_semantics.direction(). Consumers filter on this, never
    # on transaction_type strings.
    direction = Column(String(4), index=True)
    trade_date = Column(Date, index=True)
    disclosure_date = Column(Date, index=True)
    source = Column(String)            # house | senate
    raw_data = Column(Text)
    # Cached risk classification (LOW/MEDIUM/HIGH). Computed by routers.trades._risk_level
    # and refreshed by the daily scheduler job. Storing it as a column lets the
    # /trades risk_level filter become a SQL predicate instead of an over-fetch.
    risk_level = Column(String(8), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    politician = relationship("Politician", back_populates="trades")
