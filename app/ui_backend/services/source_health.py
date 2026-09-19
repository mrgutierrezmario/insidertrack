"""
Freshness bookkeeping for every external data source.

Each sync records its outcome here (one app_settings row per source). The
point is to notice quietly-broken scrapers: a government site changes a
column header, the fetcher catches the exception and returns 0, and nothing
tells anyone. /health surfaces the per-source state and a daily job emails
the admin when a source is failing or has stopped producing rows.

States:
  ok       last run succeeded and rows have arrived within the expected window
  stale    runs succeed but no new rows for longer than the source's window
  failing  the last N runs raised
  never    no run recorded yet
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models.app_setting import AppSetting

logger = logging.getLogger(__name__)

_KEY = "source_health:{source}"
FAILING_AFTER = 3  # consecutive failures before a source is "failing"

# How long a healthy source may go without producing a new row. Congress
# files continuously (recess weeks included); Form 4 is daily; 13F is
# quarterly so the run cadence matters more than new rows.
SOURCES = {
    "senate": {"label": "Senate EFD",            "max_quiet_days": 14},
    "house":  {"label": "House Clerk PTRs",      "max_quiet_days": 14},
    "form4":  {"label": "SEC Form 4",            "max_quiet_days": 10},
    "whale":  {"label": "SEC 13F (whales)",      "max_quiet_days": 120},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(db: Session, source: str) -> dict:
    row = db.query(AppSetting).filter(AppSetting.key == _KEY.format(source=source)).first()
    if not row or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except ValueError:
        return {}


def record(db: Session, source: str, *, ok: bool, new_rows: int = 0,
           error: Optional[str] = None, detail: Optional[dict] = None) -> None:
    """Upsert the outcome of one run. Never raises — health bookkeeping must
    not take a sync down with it."""
    try:
        prev = _load(db, source)
        now = _now().isoformat()
        state = {
            "last_run_at": now,
            "last_ok": ok,
            "last_error": None if ok else (error or "unknown error")[:500],
            "last_new_rows": new_rows if ok else None,
            "last_success_at": now if ok else prev.get("last_success_at"),
            "last_new_rows_at": now if (ok and new_rows > 0) else prev.get("last_new_rows_at"),
            "consecutive_failures": 0 if ok else int(prev.get("consecutive_failures", 0)) + 1,
            "detail": detail or {},
        }
        key = _KEY.format(source=source)
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = json.dumps(state)
        else:
            db.add(AppSetting(key=key, value=json.dumps(state)))
        db.commit()
    except Exception as exc:
        logger.warning(f"source_health.record({source}) failed: {exc}")
        db.rollback()


def _status(source: str, st: dict) -> str:
    if not st:
        return "never"
    if int(st.get("consecutive_failures", 0)) >= FAILING_AFTER:
        return "failing"
    quiet_days = SOURCES.get(source, {}).get("max_quiet_days")
    last_rows = st.get("last_new_rows_at") or st.get("last_success_at")
    if quiet_days and last_rows:
        age = _now() - datetime.fromisoformat(last_rows)
        if age > timedelta(days=quiet_days):
            return "stale"
    return "ok"


def summary(db: Session) -> dict:
    """Per-source state plus an overall verdict for /health and the admin UI."""
    sources = {}
    for source, meta in SOURCES.items():
        st = _load(db, source)
        sources[source] = {
            "label": meta["label"],
            "status": _status(source, st),
            "last_run_at": st.get("last_run_at"),
            "last_success_at": st.get("last_success_at"),
            "last_new_rows_at": st.get("last_new_rows_at"),
            "last_new_rows": st.get("last_new_rows"),
            "last_error": st.get("last_error"),
            "consecutive_failures": st.get("consecutive_failures", 0),
        }
    statuses = {s["status"] for s in sources.values()}
    overall = "failing" if "failing" in statuses else "stale" if "stale" in statuses else "ok"
    return {"status": overall, "sources": sources}


def problems(db: Session) -> list[dict]:
    """Sources that need a human — used by the daily admin email."""
    return [
        {"source": k, **v}
        for k, v in summary(db)["sources"].items()
        if v["status"] in ("failing", "stale")
    ]
