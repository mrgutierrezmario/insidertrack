from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from routers.access import require_admin
from sqlalchemy.orm import Session

from database import get_db
from models.analysis import DailyAnalysis
from services.analyzer import run_analysis

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/latest")
def get_latest_analysis(db: Session = Depends(get_db)):
    results = {}
    for period in ("morning", "midday", "evening"):
        a = (
            db.query(DailyAnalysis)
            .filter(DailyAnalysis.period == period)
            .order_by(DailyAnalysis.created_at.desc())
            .first()
        )
        results[period] = a
    return results


@router.get("/")
def list_analyses(
    period: Optional[str] = None,
    since: Optional[date] = None,
    limit: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
):
    q = db.query(DailyAnalysis)
    if period:
        q = q.filter(DailyAnalysis.period == period)
    if since:
        q = q.filter(DailyAnalysis.analysis_date >= since)
    return q.order_by(DailyAnalysis.created_at.desc()).limit(limit).all()


@router.post("/run/{period}")
def trigger_analysis(period: str, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    if period not in ("morning", "midday", "evening"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="period must be morning | midday | evening")
    result = run_analysis(db, period)
    return result
