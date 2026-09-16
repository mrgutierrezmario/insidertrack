"""
APScheduler jobs:
  08:00 — morning analysis + congressional sync + email
  12:00 — midday analysis + email
  18:00 — evening analysis + email
All times are Eastern (America/New_York).
"""

import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from database import SessionLocal
from services.analyzer import run_analysis
from services.congress_fetcher import sync_all
from services.email_sender import send_report
from services.outcome_tracker import fill_outcomes, snapshot_signals
from services.alert_engine import evaluate_alerts
from services.form4_fetcher import sync_form4_for_tickers
from services.market_data import warm_price_history
from services import fed_fetcher

logger = logging.getLogger(__name__)

# Persistent jobstore — next-run times survive restarts, so a scheduled job
# isn't lost if the process is down at exactly its cron minute. Combined with
# `replace_existing=True` on add_job, the same DB row is upserted on each
# startup so we always run the *current* function definition.
scheduler = BackgroundScheduler(
    timezone="America/New_York",
    jobstores={"default": SQLAlchemyJobStore(url=settings.database_url, tablename="apscheduler_jobs")},
)


def _get_subscribers_for_period(db, period: str) -> list[str]:
    from models.subscriber import EmailSubscriber
    col = f"subscribe_{period}"
    rows = (
        db.query(EmailSubscriber)
        .filter(
            EmailSubscriber.is_active == True,  # noqa: E712
            getattr(EmailSubscriber, col) == True,  # noqa: E712
        )
        .all()
    )
    return [r.email for r in rows]


def _run_and_email(period: str, sync: bool = False):
    with SessionLocal() as db:
        if sync:
            try:
                sync_all(db)
            except Exception as exc:
                # Failure is recorded by sync_all (persisted + logged); don't let
                # it abort the analysis + email for the rest of the job.
                logger.warning(f"Congressional sync failed during {period} job: {exc}")
        analysis = run_analysis(db, period)
        recipients = _get_subscribers_for_period(db, period)
        if recipients:
            send_report(analysis, recipients)


def _morning_job():
    logger.info("Running morning job: sync + analysis + email")
    _run_and_email("morning", sync=True)


def _midday_job():
    logger.info("Running midday analysis + email")
    _run_and_email("midday")


def _evening_job():
    logger.info("Running evening analysis + email")
    _run_and_email("evening")




def _outcome_snapshot_job():
    logger.info("Running daily signal outcome snapshot")
    with SessionLocal() as db:
        snapshot_signals(db)


def _outcome_fill_job():
    logger.info("Running daily outcome fill")
    with SessionLocal() as db:
        fill_outcomes(db)


def _alert_job():
    logger.info("Running alert evaluation")
    with SessionLocal() as db:
        evaluate_alerts(db)


def _form4_job():
    logger.info("Running Form 4 corporate-insider sync")
    with SessionLocal() as db:
        from routers.insiders import _tracked_tickers
        tickers = _tracked_tickers(db)
        if tickers:
            sync_form4_for_tickers(db, tickers)


def _warm_history_job():
    logger.info("Warming daily price-history cache")
    with SessionLocal() as db:
        from routers.signals import _bullish_label  # noqa: F401  (ensure module import)
        from models.politician import Politician
        from models.trade import Trade
        rows = (
            db.query(Trade.ticker)
            .join(Politician)
            .filter(Politician.is_tracked == True)  # noqa: E712
            .distinct()
            .all()
        )
        tickers = sorted({r[0] for r in rows if r[0]})
        if tickers:
            warm_price_history(tickers)


def _fed_sync_job():
    logger.info("Running Fed officials disclosure sync")
    from database import SessionLocal
    with SessionLocal() as db:
        fed_fetcher.sync_all(db)


def _risk_refresh_job():
    """Recompute the cached Trade.risk_level for every row."""
    from routers.trades import refresh_risk_levels
    with SessionLocal() as db:
        changed = refresh_risk_levels(db)
        logger.info(f"Risk-level refresh: {changed} rows updated")


def _market_cache_cleanup_job():
    """Sweep expired rows from the L2 market_cache table."""
    from services.persistent_cache import cache_delete_expired
    deleted = cache_delete_expired()
    if deleted:
        logger.info(f"Market cache cleanup: removed {deleted} expired entries")


def _db_backup_job():
    """Daily pg_dump → BACKUP_DIR; keep the last 7. See services/db_backup.py."""
    from services.db_backup import run_backup, prune_old
    if run_backup():
        prune_old()


def _watchlist_orphan_cleanup_job():
    """
    Delete WatchlistOwner rows with no associated items that haven't been
    touched in 180+ days. These accumulate when users add then remove their
    tickers, or when recovery rotations leave a stale token nobody recovers.
    Active owners (any recent last_used_at, or any items) are never touched.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import not_, exists
    from models.watchlist import WatchlistItem, WatchlistOwner
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    with SessionLocal() as db:
        deleted = (
            db.query(WatchlistOwner)
            .filter(
                # No watchlist items associated with this email
                not_(exists().where(WatchlistItem.email == WatchlistOwner.email)),
                # Either dormant for >180d or never used and created >180d ago
                (
                    (WatchlistOwner.last_used_at < cutoff) |
                    ((WatchlistOwner.last_used_at.is_(None)) & (WatchlistOwner.created_at < cutoff))
                ),
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            logger.info(f"Watchlist orphan cleanup: removed {deleted} dormant owner(s)")


def start_scheduler():
    # replace_existing=True so the persistent jobstore row is upserted on each
    # startup — we always run the current function reference, not a stale one.
    common = {"misfire_grace_time": 600, "replace_existing": True}
    scheduler.add_job(_morning_job, CronTrigger(hour=8, minute=0), id="morning", **common)
    scheduler.add_job(_midday_job, CronTrigger(hour=12, minute=0), id="midday", **common)
    scheduler.add_job(_evening_job, CronTrigger(hour=18, minute=0), id="evening", **common)
    scheduler.add_job(_outcome_snapshot_job, CronTrigger(hour=7, minute=0), id="outcome_snapshot", **common)
    scheduler.add_job(_outcome_fill_job, CronTrigger(hour=7, minute=30), id="outcome_fill", **common)
    scheduler.add_job(_form4_job, CronTrigger(hour=6, minute=30), id="form4_sync", **common)
    scheduler.add_job(_warm_history_job, CronTrigger(hour=6, minute=45), id="warm_history", **common)
    scheduler.add_job(_alert_job, CronTrigger(hour="8,12,18", minute=15), id="alert_eval", **common)
    scheduler.add_job(_fed_sync_job, CronTrigger(hour=7, minute=15), id="fed_sync", **common)
    # Risk classification depends on trade age — refresh once a day so old rows
    # bucket correctly without the /trades read path doing the work.
    scheduler.add_job(_risk_refresh_job, CronTrigger(hour=5, minute=30), id="risk_refresh", **common)
    # Sweep expired L2 market_cache rows hourly — the index keeps lookups fast
    # but a clean table is nicer to inspect and bounds disk usage.
    scheduler.add_job(_market_cache_cleanup_job, CronTrigger(minute=17), id="market_cache_cleanup", **common)
    # Daily DB backup at 04:00 ET — earliest slot before anything else runs.
    scheduler.add_job(_db_backup_job, CronTrigger(hour=4, minute=0), id="db_backup", **common)
    # Weekly cleanup of dormant WatchlistOwner rows (Sundays 03:30 ET).
    scheduler.add_job(_watchlist_orphan_cleanup_job, CronTrigger(day_of_week="sun", hour=3, minute=30), id="watchlist_orphan_cleanup", **common)
    scheduler.start()
    logger.info("Scheduler started (persistent jobstore) — Form4 06:30, snapshot 07:00, fill 07:30, analysis 08/12/18, alerts 08/12/18:15 ET")


def stop_scheduler():
    scheduler.shutdown()
