from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from database import Base


class EmailSubscriber(Base):
    __tablename__ = "email_subscribers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    subscribe_morning = Column(Boolean, default=True)
    subscribe_midday = Column(Boolean, default=True)
    subscribe_evening = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
