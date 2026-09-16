from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class SiteAccess(Base):
    __tablename__ = "site_access"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(100), index=True)
    email = Column(String(255), nullable=True)
    user_agent = Column(Text, nullable=True)
    agreed_at = Column(DateTime(timezone=True), server_default=func.now())
