from fastapi import APIRouter, Depends, HTTPException, Query
from routers.access import require_admin
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.politician import Politician
from models.trade import Trade

router = APIRouter(prefix="/politicians", tags=["politicians"])


class PoliticianCreate(BaseModel):
    name: str
    chamber: str        # house | senate
    party: str = ""
    state: str = ""
    description: str = ""
    why_tracked: str = ""
    is_tracked: bool = True


class PoliticianUpdate(BaseModel):
    description: str | None = None
    why_tracked: str | None = None
    party: str | None = None
    state: str | None = None


def _serialize(p: Politician, trade_count: int = 0) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "chamber": p.chamber,
        "party": p.party,
        "state": p.state,
        "is_tracked": p.is_tracked,
        "description": p.description or "",
        "why_tracked": p.why_tracked or "",
        "trade_count": trade_count,
    }


@router.get("/")
def list_politicians(
    tracked_only: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    counts = dict(
        db.query(Trade.politician_id, func.count(Trade.id))
        .group_by(Trade.politician_id)
        .all()
    )
    q = db.query(Politician)
    if tracked_only:
        q = q.filter(Politician.is_tracked == True)  # noqa: E712
    rows = q.order_by(Politician.name).offset(offset).limit(limit).all()
    return [_serialize(p, counts.get(p.id, 0)) for p in rows]


@router.post("/", status_code=201)
def create_politician(body: PoliticianCreate, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    existing = db.query(Politician).filter(Politician.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"'{body.name}' already exists (id={existing.id})")
    p = Politician(
        name=body.name,
        chamber=body.chamber.lower(),
        party=body.party,
        state=body.state,
        description=body.description,
        why_tracked=body.why_tracked,
        is_tracked=body.is_tracked,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize(p)


@router.get("/{politician_id}")
def get_politician(politician_id: int, db: Session = Depends(get_db)):
    p = db.query(Politician).filter(Politician.id == politician_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Politician not found")
    count = db.query(func.count(Trade.id)).filter(Trade.politician_id == politician_id).scalar() or 0
    return _serialize(p, count)


@router.patch("/{politician_id}")
def update_politician(politician_id: int, body: PoliticianUpdate, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.query(Politician).filter(Politician.id == politician_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Politician not found")
    if body.description is not None:
        p.description = body.description
    if body.why_tracked is not None:
        p.why_tracked = body.why_tracked
    if body.party is not None:
        p.party = body.party
    if body.state is not None:
        p.state = body.state
    db.commit()
    return _serialize(p)


@router.patch("/{politician_id}/track")
def toggle_track(politician_id: int, track: bool, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.query(Politician).filter(Politician.id == politician_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Politician not found")
    p.is_tracked = track
    db.commit()
    return {"id": politician_id, "is_tracked": track}


@router.delete("/{politician_id}", status_code=204)
def delete_politician(
    politician_id: int,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    p = db.query(Politician).filter(Politician.id == politician_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Politician not found")
    db.delete(p)
    db.commit()


@router.get("/{politician_id}/trades")
def get_politician_trades(politician_id: int, limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    from routers.trades import _risk_level
    trades = (
        db.query(Trade)
        .filter(Trade.politician_id == politician_id)
        .order_by(Trade.trade_date.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "ticker": t.ticker,
            "asset_name": t.asset_name,
            "transaction_type": t.transaction_type,
            "direction": t.direction,
            "asset_type": t.asset_type,
            "owner": t.owner,
            "amount_range": t.amount_range,
            "amount_low": t.amount_low,
            "amount_high": t.amount_high,
            "trade_date": t.trade_date,
            "disclosure_date": t.disclosure_date,
            "source": t.source,
            "risk_level": _risk_level(t),
        }
        for t in trades
    ]
