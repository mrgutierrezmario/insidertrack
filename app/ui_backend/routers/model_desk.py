"""The AI Desk: today's brief and calls, the running scorecard, history."""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from routers.access import require_admin
from services import model_desk

router = APIRouter(prefix="/ai-desk", tags=["ai-desk"])


@router.get("/today")
def desk_today(db: Session = Depends(get_db)):
    return model_desk.today(db)


@router.get("/calls")
def desk_calls(limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)):
    return {"items": model_desk.history(db, limit), "stats": model_desk.stats(db)}


@router.post("/generate")
def desk_generate(background_tasks: BackgroundTasks, force: bool = False, _: None = Depends(require_admin)):
    """Admin: (re)generate today's brief now instead of waiting for 8:30 ET."""
    def _run():
        from database import SessionLocal
        with SessionLocal() as s:
            model_desk.resolve_calls(s)
            model_desk.generate_brief(s, force=force)
    background_tasks.add_task(_run)
    return {"status": "started"}
