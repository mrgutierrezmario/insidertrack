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
