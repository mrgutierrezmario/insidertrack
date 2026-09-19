from sqlalchemy import Column, Integer, String, Boolean, Text
from sqlalchemy.orm import relationship
from database import Base


class Politician(Base):
    __tablename__ = "politicians"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    chamber = Column(String, nullable=False)  # house | senate
    party = Column(String)
    state = Column(String)
    # Every member is tracked by default — the signal universe is "all
    # congressional trades". Untracking is an admin opt-out (mute) that removes
    # a member's trades from signals, analysis, alerts and outcome snapshots.
    is_tracked = Column(Boolean, default=True, server_default="true", nullable=False)
    description = Column(Text, default="")
    why_tracked = Column(Text, default="")

    trades = relationship("Trade", back_populates="politician")
