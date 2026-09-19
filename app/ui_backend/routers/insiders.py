"""Corporate insider (SEC Form 4) transactions."""

from datetime import date, timedelta
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
def insider_summary(days: int = Query(default=90, ge=1, le=730), limit: int = Query(default=200, ge=1, le=1000),
                    db: Session = Depends(get_db)):
    """Per-ticker buy/sell counts from corporate insiders in the last `days`."""
    from sqlalchemy import case, func
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(
            Form4Transaction.ticker,
            func.sum(case((Form4Transaction.transaction_type == "buy", 1), else_=0)).label("buys"),
            func.sum(case((Form4Transaction.transaction_type == "sell", 1), else_=0)).label("sells"),
            func.sum(case((Form4Transaction.transaction_type.notin_(["buy", "sell"]), 1), else_=0)).label("other"),
        )
        .filter(Form4Transaction.transaction_date >= cutoff, Form4Transaction.ticker.isnot(None))
        .group_by(Form4Transaction.ticker)
        .order_by((func.sum(case((Form4Transaction.transaction_type.in_(["buy", "sell"]), 1), else_=0))).desc())
        .limit(limit)
        .all()
    )
    return [{"ticker": t, "buys": int(b or 0), "sells": int(s or 0), "other": int(o or 0)} for t, b, s, o in rows]


@router.get("/clusters")
def insider_clusters(days: int = Query(default=30, ge=1, le=365), min_buyers: int = Query(default=2, ge=1, le=10),
                     limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    """Cluster buys market-wide: tickers where `min_buyers`+ distinct insiders
    bought on the open market in the last `days`, by dollars bought. This is
    the Form 4 signal that lives outside the congressional universe."""
    from sqlalchemy import func
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(
            Form4Transaction.ticker,
            func.max(Form4Transaction.company_name).label("company"),
            func.count(func.distinct(Form4Transaction.insider_name)).label("buyers"),
            func.count(Form4Transaction.id).label("buys"),
            func.sum(Form4Transaction.value).label("dollars"),
            func.max(Form4Transaction.transaction_date).label("last_buy"),
        )
        .filter(Form4Transaction.transaction_type == "buy", Form4Transaction.transaction_date >= cutoff,
                Form4Transaction.ticker.isnot(None))
        .group_by(Form4Transaction.ticker)
        .having(func.count(func.distinct(Form4Transaction.insider_name)) >= min_buyers)
        .order_by(func.sum(Form4Transaction.value).desc())
        .limit(limit)
        .all()
    )
    return {"days": days, "min_buyers": min_buyers, "items": [
        {"ticker": t, "company": c, "buyers": int(n), "buys": int(b), "dollars": int(d or 0),
         "last_buy": l.isoformat() if l else None}
        for t, c, n, b, d, l in rows
    ]}


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
