from sqlalchemy import Column, Integer, String, Date, DateTime, Text, JSON
from sqlalchemy.sql import func
from database import Base


class DailyAnalysis(Base):
    __tablename__ = "daily_analyses"

    id = Column(Integer, primary_key=True, index=True)
    analysis_date = Column(Date, index=True)
    period = Column(String, nullable=False)   # morning | midday | evening
    tickers_bullish = Column(JSON)            # list of tickers with buy signal
    tickers_bearish = Column(JSON)            # list of tickers with sell signal
    top_movers = Column(JSON)                 # price movement on tracked tickers
    summary = Column(Text)
    signals = Column(JSON)                    # full signal objects
    created_at = Column(DateTime(timezone=True), server_default=func.now())
