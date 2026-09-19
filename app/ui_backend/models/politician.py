from sqlalchemy import Column, Date, Float, Integer, String, Boolean, Text
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
    # Identity across the spellings the House index and EFD use for one
    # person ("Scott Franklin" / "Scott Mr Franklin" / "C. Scott Franklin"):
    # the congress-legislators bioguide id when the roster knows them, and a
    # normalized "first last" key either way. See congress_fetcher._name_key.
    bioguide_id = Column(String(12), index=True)
    name_key = Column(String(80), index=True)
    description = Column(Text, default="")
    # Track-record weight applied to this member's trades in the Congress
    # sub-score: 0.5 (always wrong) … 1.5 (always right); 1.0 = unknown / too
    # few measured buys. Recomputed weekly by services.track_record.refresh_skill.
    skill_factor = Column(Float, default=1.0, server_default="1.0")
    skill_n = Column(Integer)          # buys the factor was measured on
    skill_beat_spy = Column(Float)     # 90-day beat-SPY rate, %
    skill_as_of = Column(Date)
    why_tracked = Column(Text, default="")

    trades = relationship("Trade", back_populates="politician")
