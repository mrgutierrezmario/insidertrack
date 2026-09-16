from sqlalchemy import Column, Integer, String, Float, BigInteger, Date, DateTime
from sqlalchemy.sql import func
from database import Base


class Form4Transaction(Base):
    """
    A corporate insider transaction parsed from an SEC Form 4 filing.
    These are company officers/directors (CEO, CFO, 10% owners) — distinct
    from the congressional trades stored in the `trades` table.
    """
    __tablename__ = "form4_transactions"

    id            = Column(Integer, primary_key=True, index=True)
    ticker        = Column(String(20), index=True)
    company_name  = Column(String(255))
    insider_name  = Column(String(255))
    insider_title = Column(String(255))
    relationship  = Column(String(60))   # Officer | Director | 10% Owner

    transaction_code = Column(String(4))  # P=purchase S=sale A=grant M=exercise ...
    transaction_type = Column(String(20)) # buy | sell | other
    shares        = Column(BigInteger)
    price         = Column(Float)
    value         = Column(BigInteger)
    transaction_date = Column(Date, index=True)
    filing_date   = Column(Date, index=True)

    accession     = Column(String(40), index=True)
    source_url    = Column(String(400))
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
