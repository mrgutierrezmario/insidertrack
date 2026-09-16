"""Federal Reserve officials and their financial disclosures."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from routers.access import require_admin
from sqlalchemy.orm import Session

from database import get_db
from models.fed_official import FedOfficial, FedTrade

router = APIRouter(prefix="/fed", tags=["fed"])


def _serialize_official(o: FedOfficial, trade_count: int = 0) -> dict:
    return {
        "id": o.id,
        "name": o.name,
        "title": o.title,
        "role": o.role,
        "district": o.district,
        "is_fomc_voter": o.is_fomc_voter,
        "appointed_by": o.appointed_by,
        "term_expires": o.term_expires,
        "party": o.party,
        "bio": o.bio or "",
        "disclosure_url": o.disclosure_url,
        "is_active": o.is_active,
        "trade_count": trade_count,
    }


def _serialize_trade(t: FedTrade) -> dict:
    return {
        "id": t.id,
        "official_id": t.official_id,
        "official_name": t.official.name if t.official else None,
        "official_title": t.official.title if t.official else None,
        "ticker": t.ticker,
        "asset_name": t.asset_name,
        "transaction_type": t.transaction_type,
        "amount_range": t.amount_range,
        "shares": t.shares,
        "price": t.price,
        "trade_date": t.trade_date.isoformat() if t.trade_date else None,
        "disclosure_date": t.disclosure_date.isoformat() if t.disclosure_date else None,
        "filing_year": t.filing_year,
        "source": t.source,
        "source_url": t.source_url,
    }


@router.get("/officials")
def list_officials(db: Session = Depends(get_db)):
    from sqlalchemy import func
    counts = dict(
        db.query(FedTrade.official_id, func.count(FedTrade.id))
        .group_by(FedTrade.official_id)
        .all()
    )
    officials = (
        db.query(FedOfficial)
        .filter(FedOfficial.is_active == True)  # noqa: E712
        .order_by(FedOfficial.role, FedOfficial.name)
        .all()
    )
    return [_serialize_official(o, counts.get(o.id, 0)) for o in officials]


@router.get("/trades")
def list_trades(
    official_id: int = Query(default=0),
    ticker: str = Query(default=""),
    transaction_type: str = Query(default=""),
    after: Optional[date] = None,
    limit: int = Query(default=100, le=300),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = (
        db.query(FedTrade)
        .join(FedOfficial)
        .order_by(FedTrade.trade_date.desc())
    )
    if official_id:
        q = q.filter(FedTrade.official_id == official_id)
    if ticker:
        q = q.filter(FedTrade.ticker == ticker.upper())
    if transaction_type:
        q = q.filter(FedTrade.transaction_type == transaction_type)
    if after:
        q = q.filter(FedTrade.trade_date >= after)
    rows = q.offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [_serialize_trade(t) for t in rows], "offset": offset, "limit": limit, "has_more": has_more}


@router.post("/sync")
def sync_fed(background_tasks: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Seed officials + fetch latest OGE disclosures in background."""
    from services.fed_fetcher import sync_all

    def _run():
        from database import SessionLocal
        with SessionLocal() as s:
            sync_all(s)

    background_tasks.add_task(_run)
    return {"status": "sync started"}


@router.post("/seed")
def seed_officials_endpoint(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Immediately seed officials roster (fast — no network calls)."""
    from services.fed_fetcher import seed_officials, seed_trades
    officials_added = seed_officials(db)
    trades_added = seed_trades(db)
    return {"officials_added": officials_added, "trades_seeded": trades_added}
