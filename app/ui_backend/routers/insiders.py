"""Corporate insider (SEC Form 4) transactions."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from routers.access import require_admin
from sqlalchemy.orm import Session

from database import get_db
from models.insider import Form4Transaction
from models.politician import Politician
from models.trade import Trade
from services.tickers import tracked_tickers as _tracked_tickers  # re-exported for back-compat

router = APIRouter(prefix="/insiders", tags=["insiders"])


@router.get("/")
def list_transactions(
    ticker: str = "",
    transaction_type: str = "",
    after: Optional[date] = None,
    limit: int = Query(default=100, le=300),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Form4Transaction).order_by(Form4Transaction.transaction_date.desc())
    if ticker:
        q = q.filter(Form4Transaction.ticker == ticker.upper())
    if transaction_type:
        q = q.filter(Form4Transaction.transaction_type == transaction_type)
    if after:
        q = q.filter(Form4Transaction.transaction_date >= after)
    rows = q.offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "id": r.id,
            "ticker": r.ticker,
            "company_name": r.company_name,
            "insider_name": r.insider_name,
            "insider_title": r.insider_title,
            "relationship": r.relationship,
            "transaction_code": r.transaction_code,
            "transaction_type": r.transaction_type,
            "shares": r.shares,
            "price": r.price,
            "value": r.value,
            "transaction_date": r.transaction_date.isoformat() if r.transaction_date else None,
            "filing_date": r.filing_date.isoformat() if r.filing_date else None,
            "source_url": r.source_url,
        }
        for r in rows
    ]
    return {"items": items, "offset": offset, "limit": limit, "has_more": has_more}


@router.get("/summary")
def insider_summary(db: Session = Depends(get_db)):
    """Per-ticker buy/sell counts from corporate insiders."""
    rows = db.query(Form4Transaction).all()
    by_ticker: dict[str, dict] = {}
    for r in rows:
        d = by_ticker.setdefault(r.ticker, {"ticker": r.ticker, "buys": 0, "sells": 0, "other": 0})
        if r.transaction_type == "buy":
            d["buys"] += 1
        elif r.transaction_type == "sell":
            d["sells"] += 1
        else:
            d["other"] += 1
    return sorted(by_ticker.values(), key=lambda x: x["buys"] + x["sells"], reverse=True)


@router.post("/sync")
def sync_insiders(background_tasks: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Pull recent Form 4 filings from SEC EDGAR for every tracked ticker.

    Runs in the background — hundreds of tickers at SEC's rate limit is
    minutes, and the single worker must not block. The outcome is recorded
    per source (see /health "data" and Admin → Data sources)."""
    from services.scheduler import _form4_job
    tickers = _tracked_tickers(db)
    if not tickers:
        return {"status": "no tracked tickers", "tickers": 0}
    background_tasks.add_task(_form4_job)
    return {"status": "started", "tickers": len(tickers)}
