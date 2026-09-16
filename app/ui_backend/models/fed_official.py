from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class FedOfficial(Base):
    __tablename__ = "fed_officials"

    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String(255), unique=True, nullable=False, index=True)
    title          = Column(String(255))
    role           = Column(String(60))    # board | regional_president
    district       = Column(String(100))   # "New York", "Chicago", etc. (regional only)
    is_fomc_voter  = Column(Boolean, default=True)
    appointed_by   = Column(String(100))   # President who appointed/nominated
    term_expires   = Column(String(20))
    party          = Column(String(4))     # D | R | I — appointing president's party
    bio            = Column(Text, default="")
    disclosure_url = Column(String(500))
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    trades = relationship("FedTrade", back_populates="official", cascade="all, delete-orphan")


class FedTrade(Base):
    __tablename__ = "fed_trades"

    id               = Column(Integer, primary_key=True, index=True)
    official_id      = Column(Integer, ForeignKey("fed_officials.id"), nullable=False)
    ticker           = Column(String(20), index=True)
    asset_name       = Column(String(255))
    transaction_type = Column(String(20))  # purchase | sale | other
    amount_range     = Column(String(100))
    shares           = Column(Float, nullable=True)
    price            = Column(Float, nullable=True)
    trade_date       = Column(Date, index=True)
    disclosure_date  = Column(Date, nullable=True)
    filing_year      = Column(Integer, nullable=True)
    source_url       = Column(String(500))
    source           = Column(String(60), default="oge")  # oge | fed | manual
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    official = relationship("FedOfficial", back_populates="trades")
