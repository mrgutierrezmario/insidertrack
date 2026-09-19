from fastapi import APIRouter, BackgroundTasks, Depends, Query
from routers.access import require_admin
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.whale import WhaleHolder, WhalePosition

router = APIRouter(prefix="/whales", tags=["whales"])

CHANGE_EMOJI = {"new": "🆕", "increased": "↑", "decreased": "↓", "closed": "✕", "stable": "—"}


def _fmt_value(v: int | None) -> str:
    if not v:
        return "—"
    if v >= 1_000_000_000:
        return f"${v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.0f}M"
    return f"${v:,}"


@router.get("/")
def list_whales(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    holders = (
        db.query(WhaleHolder)
        .order_by(WhaleHolder.name)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": h.id,
            "name": h.name,
            "cik": h.cik,
            "holder_type": h.holder_type,
            "is_tracked": h.is_tracked,
            "position_count": len(h.positions),
        }
        for h in holders
    ]


@router.get("/feed")
def whale_feed(
    holder_id: int | None = None,
    change_type: str | None = None,
    ticker: str | None = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    q = (
        db.query(WhalePosition)
        .options(joinedload(WhalePosition.holder))
        .join(WhaleHolder)
        .filter(WhaleHolder.is_tracked == True)  # noqa: E712
        .order_by(WhalePosition.filing_date.desc(), WhalePosition.value_usd.desc())
    )
    if holder_id:
        q = q.filter(WhalePosition.holder_id == holder_id)
    if change_type:
        q = q.filter(WhalePosition.change_type == change_type)
    if ticker:
        q = q.filter(WhalePosition.ticker == ticker.upper())

    positions = q.limit(limit).all()

    return [
        {
            "id": p.id,
            "ticker": p.ticker,
            "company_name": p.company_name,
            "shares": p.shares,
            "value_usd": p.value_usd,
            "value_fmt": _fmt_value(p.value_usd),
            "filing_date": str(p.filing_date),
            "quarter": p.quarter,
            "change_type": p.change_type,
            "holder": {
                "id": p.holder.id,
                "name": p.holder.name,
            } if p.holder else None,
        }
        for p in positions
    ]


@router.get("/{holder_id}/positions")
def holder_positions(holder_id: int, db: Session = Depends(get_db)):
    holder = db.query(WhaleHolder).filter(WhaleHolder.id == holder_id).first()
    if not holder:
        from fastapi import HTTPException
        raise HTTPException(404, detail="Whale holder not found")

    positions = (
        db.query(WhalePosition)
        .filter(WhalePosition.holder_id == holder_id)
        .order_by(WhalePosition.value_usd.desc())
        .all()
    )
    return {
        "holder": {"id": holder.id, "name": holder.name, "cik": holder.cik},
        "positions": [
            {
                "ticker": p.ticker,
                "company_name": p.company_name,
                "shares": p.shares,
                "value_fmt": _fmt_value(p.value_usd),
                "filing_date": str(p.filing_date),
                "quarter": p.quarter,
                "change_type": p.change_type,
            }
            for p in positions
        ],
    }


@router.post("/sync")
def sync_whales(background_tasks: BackgroundTasks, _: None = Depends(require_admin)):
    """Fetch the latest 13F filings from SEC EDGAR in the background; the
    outcome is recorded per source (Admin → Data sources)."""
    from services.scheduler import _whale_sync_job
    background_tasks.add_task(_whale_sync_job)
    return {"status": "started"}


@router.get("/{holder_id}/detail")
def whale_detail(holder_id: int, db: Session = Depends(get_db)):
    """Holder profile: summary stats, change breakdown, and top holdings."""
    from fastapi import HTTPException
    holder = db.query(WhaleHolder).filter(WhaleHolder.id == holder_id).first()
    if not holder:
        raise HTTPException(404, detail="Whale holder not found")

    positions = (
        db.query(WhalePosition)
        .filter(WhalePosition.holder_id == holder_id)
        .order_by(WhalePosition.value_usd.desc())
        .all()
    )

    total_value = sum(p.value_usd or 0 for p in positions)
    change_breakdown = {"new": 0, "increased": 0, "decreased": 0, "closed": 0, "stable": 0}
    for p in positions:
        ct = p.change_type or "stable"
        change_breakdown[ct] = change_breakdown.get(ct, 0) + 1

    quarters = sorted({p.quarter for p in positions if p.quarter}, reverse=True)
    latest_quarter = quarters[0] if quarters else None

    holdings = [
        {
            "ticker": p.ticker,
            "company_name": p.company_name,
            "shares": p.shares,
            "value_usd": p.value_usd,
            "value_fmt": _fmt_value(p.value_usd),
            "weight_pct": round((p.value_usd or 0) / total_value * 100, 1) if total_value else 0,
            "change_type": p.change_type,
            "quarter": p.quarter,
            "filing_date": str(p.filing_date),
        }
        for p in positions
    ]

    conviction = [h for h in holdings if h["change_type"] in ("new", "increased")][:10]

    return {
        "holder": {
            "id": holder.id,
            "name": holder.name,
            "cik": holder.cik,
            "holder_type": holder.holder_type,
        },
        "summary": {
            "position_count": len(positions),
            "total_value": total_value,
            "total_value_fmt": _fmt_value(total_value),
            "latest_quarter": latest_quarter,
            "quarters": quarters,
            "change_breakdown": change_breakdown,
        },
        "conviction_buys": conviction,
        "top_holdings": holdings[:25],
        "all_holdings": holdings,
    }
