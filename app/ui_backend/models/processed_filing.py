from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, func

from database import Base


class ProcessedFiling(Base):
    """Records every congressional filing (PTR) we've already downloaded and
    parsed — including ones that yielded no listed-stock trades (bonds, funds,
    options). Without this, those zero-trade filings would be re-downloaded on
    every sync because nothing about them lands in the trades table.
    """

    __tablename__ = "processed_filings"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)   # house | senate
    doc_id = Column(String, index=True)   # House DocID or Senate PTR uuid
    processed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "doc_id", name="uq_processed_source_doc"),
    )
