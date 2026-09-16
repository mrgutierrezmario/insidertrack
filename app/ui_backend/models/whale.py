from sqlalchemy import Column, Integer, String, BigInteger, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class WhaleHolder(Base):
    __tablename__ = "whale_holders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    cik = Column(String, unique=True)
    holder_type = Column(String)        # fund | individual
    is_tracked = Column(Boolean, default=False)

    positions = relationship("WhalePosition", back_populates="holder")


class WhalePosition(Base):
    __tablename__ = "whale_positions"

    id = Column(Integer, primary_key=True, index=True)
    holder_id = Column(Integer, ForeignKey("whale_holders.id"), nullable=False)
    ticker = Column(String, index=True)
    company_name = Column(String)
    shares = Column(BigInteger)
    value_usd = Column(BigInteger)
    filing_date = Column(Date, index=True)
    quarter = Column(String)            # e.g. "2024-Q1"
    change_type = Column(String)        # new | increased | decreased | closed
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    holder = relationship("WhaleHolder", back_populates="positions")
