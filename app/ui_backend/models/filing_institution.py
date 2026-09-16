from sqlalchemy import Column, Integer, String
from database import Base


class FilingInstitution(Base):
    __tablename__ = "filing_institutions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    cik = Column(String(10), nullable=False, unique=True)
