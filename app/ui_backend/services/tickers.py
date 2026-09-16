"""Shared helpers for resolving the set of tracked tickers."""

from sqlalchemy.orm import Session

from models.politician import Politician
from models.trade import Trade


def tracked_tickers(db: Session) -> list[str]:
    """Distinct tickers traded by any tracked politician, sorted alphabetically."""
    rows = (
        db.query(Trade.ticker)
        .join(Politician)
        .filter(Politician.is_tracked == True)  # noqa: E712
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]})
