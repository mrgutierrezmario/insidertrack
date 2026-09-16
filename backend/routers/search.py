from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.fed_official import FedOfficial
from models.politician import Politician
from models.trade import Trade

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/")
def search(q: str = Query(min_length=1, max_length=80), db: Session = Depends(get_db)):
    if not q.strip():
        return {"politicians": [], "tickers": [], "fed_officials": []}

    politicians = (
        db.query(Politician)
        .filter(Politician.name.ilike(f"%{q}%"))
        .order_by(Politician.is_tracked.desc(), Politician.name)
        .limit(6)
        .all()
    )

    ticker_rows = (
        db.query(Trade.ticker)
        .filter(Trade.ticker.ilike(f"%{q.upper()}%"))
        .distinct()
        .limit(8)
        .all()
    )

    fed = (
        db.query(FedOfficial)
        .filter(FedOfficial.name.ilike(f"%{q}%"), FedOfficial.is_active == True)  # noqa: E712
        .order_by(FedOfficial.name)
        .limit(4)
        .all()
    )

    return {
        "politicians": [
            {"id": p.id, "name": p.name, "party": p.party, "state": p.state,
             "chamber": p.chamber, "is_tracked": p.is_tracked}
            for p in politicians
        ],
        "tickers": [r[0] for r in ticker_rows],
        "fed_officials": [
            {"id": f.id, "name": f.name, "title": f.title, "role": f.role}
            for f in fed
        ],
    }
