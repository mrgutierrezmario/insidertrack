import logging
import logging.handlers
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import init_db
from routers import access, ai, alerts, analysis, app_settings, config, earnings, fed, filings, insiders, market, model_desk, news, outcomes, politicians, search, signals, simulator, trades, watchlist, whales
from services.scheduler import start_scheduler, stop_scheduler

# ── Logging setup ─────────────────────────────────────────────────────────────
# Console handler (stderr → captured by start.sh into logs/backend.log via uvicorn).
# File handler with rotation — bounds disk usage and survives long uptimes.
# Both share one format so the rotated file matches what uvicorn captures live.
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_log_root = logging.getLogger()
_log_root.setLevel(logging.INFO)
if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in _log_root.handlers):
    _file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "backend-app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    _file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    _log_root.addHandler(_file_handler)
if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in _log_root.handlers):
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    _log_root.addHandler(_console_handler)

DIST_DIR = Path(__file__).parent.parent / "ui_frontend" / "dist"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "font-src 'self' data:;"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from database import SessionLocal
    from routers.app_settings import load_db_settings
    from routers.filings import seed_filing_institutions
    with SessionLocal() as db:
        load_db_settings(db)
        seed_filing_institutions(db)
        # Fed page is a roster (no data feed); apply the built-in roster so
        # additions/retirements land on deploy without an admin click.
        try:
            from services.fed_fetcher import seed_officials
            seed_officials(db)
        except Exception:
            logging.getLogger(__name__).exception("Fed roster seed at startup failed")
        # Backfill any new/cleared risk_level cells so the /trades filter is
        # immediately accurate — the daily scheduler job keeps them current after.
        try:
            from routers.trades import refresh_risk_levels
            refresh_risk_levels(db)
        except Exception:
            logging.getLogger(__name__).exception("risk_level backfill at startup failed")
        # Surface signal_outcomes gaps from prior downtime and retroactively
        # reconstruct what we can. Backfilled rows are flagged `is_backfilled`
        # (sentiment can't be reconstructed from Alpha Vantage — see
        # `outcome_tracker.backfill_snapshot_gaps` for the caveats).
        try:
            from services.outcome_tracker import detect_snapshot_gaps, backfill_snapshot_gaps
            gaps = detect_snapshot_gaps(db, window_days=14)
            if gaps:
                logging.getLogger(__name__).warning(
                    "signal_outcomes gaps in last 14d: %s — attempting backfill",
                    ", ".join(d.isoformat() for d in gaps),
                )
                summary = backfill_snapshot_gaps(db, window_days=14)
                logging.getLogger(__name__).info("Backfill summary: %s", summary)
        except Exception:
            logging.getLogger(__name__).exception("gap detection / backfill at startup failed")
    start_scheduler()
    # Compute the signal set once in the background so the first visitor
    # after a deploy doesn't eat the cold price fan-out (~7 s for ~140
    # tickers). Uses the same 5-minute cache the endpoint serves from.
    import threading

    def _warm_signals():
        try:
            from routers.signals import technical_signals
            with SessionLocal() as db:
                n = len(technical_signals(db).get("signals", []))
            logging.getLogger(__name__).info("Warmed signal cache: %d tickers", n)
        except Exception:
            logging.getLogger(__name__).exception("signal warm at startup failed")

    threading.Thread(target=_warm_signals, name="warm-signals", daemon=True).start()
    yield
    stop_scheduler()


from version import __version__  # noqa: E402

app = FastAPI(title="InsiderTrack API", version=__version__, lifespan=lifespan)


# ── Global exception handlers ─────────────────────────────────────────────────
# All errors return the same JSON shape: {"error": str, "detail": str|dict|None, "request_id": str}.
# HTTPException keeps its status_code; everything else returns 500. Unexpected
# errors get logged with the request_id so the caller can quote it.

def _error_payload(error: str, detail, request_id: str) -> dict:
    return {"error": error, "detail": detail, "request_id": request_id}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    return JSONResponse(
        _error_payload(exc.__class__.__name__, exc.detail, rid),
        status_code=exc.status_code,
        headers={"x-request-id": rid},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    return JSONResponse(
        _error_payload("ValidationError", exc.errors(), rid),
        status_code=422,
        headers={"x-request-id": rid},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    logging.getLogger(__name__).exception(
        "Unhandled %s on %s %s [rid=%s]", type(exc).__name__, request.method, request.url.path, rid
    )
    from services.error_log import record
    record(type(exc).__name__, f"{request.method} {request.url.path}", rid)
    return JSONResponse(
        _error_payload("InternalServerError", "An unexpected error occurred.", rid),
        status_code=500,
        headers={"x-request-id": rid},
    )


app.add_middleware(SecurityHeadersMiddleware)
# CORS allowlist: same-origin (localhost) is always trusted; the public hostname
# (the Tailscale Funnel host) is configurable via PUBLIC_DOMAIN so a rename isn't a code change.
_cors_origins = ["http://localhost:8003"]
if settings.public_domain:
    _cors_origins.append(f"https://{settings.public_domain}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trades.router)
app.include_router(politicians.router)
app.include_router(analysis.router)
app.include_router(simulator.router)
app.include_router(market.router)
app.include_router(signals.router)
app.include_router(outcomes.router)
app.include_router(alerts.router)
app.include_router(model_desk.router)
app.include_router(ai.router)
app.include_router(insiders.router)
app.include_router(watchlist.router)
app.include_router(filings.router)
app.include_router(config.router)
app.include_router(search.router)
app.include_router(whales.router)
app.include_router(fed.router)
app.include_router(access.router)
app.include_router(news.router)
app.include_router(earnings.router)
app.include_router(app_settings.router)


@app.get("/jobs/running")
def jobs_running():
    """Long-running jobs in flight — deploy/start.sh refuses to restart the
    app while any is running (a restart kills them). In-process jobs report
    from memory; the skill refresh (which may run via docker exec) leaves a
    marker in app_settings, treated as stale after 4 h."""
    from datetime import datetime, timedelta
    from database import SessionLocal
    from models.app_setting import AppSetting
    from services.congress_fetcher import get_backfill_state, get_sync_state
    from services.track_record import SKILL_JOB_KEY

    running = {}
    if get_sync_state().get("running"):
        running["congress_sync"] = get_sync_state().get("started_at")
    bf = get_backfill_state()
    if bf.get("running"):
        running["backfill"] = f"{bf.get('since')} → {bf.get('until')}{' (re-parse)' if bf.get('reparse') else ''}, phase {bf.get('phase')} {bf.get('done')}/{bf.get('total')}"
    try:
        with SessionLocal() as db:
            row = db.query(AppSetting).filter(AppSetting.key == SKILL_JOB_KEY).first()
            if row and row.value:
                started = datetime.fromisoformat(row.value)
                if datetime.now() - started < timedelta(hours=4):
                    running["skill_refresh"] = row.value
    except Exception:
        pass
    return {"running": running, "any": bool(running)}


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    from sqlalchemy import text
    from database import SessionLocal
    from services.scheduler import scheduler
    from services.outcome_tracker import detect_snapshot_gaps

    from services.source_health import summary as source_summary

    db_ok = False
    snapshot_gaps_14d = None
    sources = None
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            db_ok = True
            try:
                snapshot_gaps_14d = len(detect_snapshot_gaps(db, window_days=14))
            except Exception:
                snapshot_gaps_14d = None
            try:
                sources = source_summary(db)
            except Exception:
                sources = None
    except Exception:
        db_ok = False

    scheduler_running = bool(getattr(scheduler, "running", False))

    status = "ok" if (db_ok and scheduler_running) else "degraded"
    code = 200 if status == "ok" else 503
    return JSONResponse(
        {
            "status": status,
            "version": __version__,
            "db": db_ok,
            "scheduler": scheduler_running,
            "snapshot_gaps_14d": snapshot_gaps_14d,
            # Data freshness is reported, not enforced: a stale scraper must
            # not flip the container unhealthy (the process is fine).
            "data": sources,
            # Unhandled exceptions in the last 24 h (in-process; resets on restart).
            "errors_24h": __import__("services.error_log", fromlist=["summary"]).summary(24),
        },
        status_code=code,
    )


# Serve built frontend — must be last so API routes take priority
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    def serve_frontend(full_path: str):
        # Root-level static files from the build (favicons, manifest, logos,
        # fonts) are served as-is; anything else is a client-side route and
        # gets the SPA shell. The resolve() check keeps ".." inside dist.
        # Static pages (user guide, privacy) work without the .html extension.
        if full_path in ("guide", "privacy"):
            full_path += ".html"
        if full_path:
            candidate = (DIST_DIR / full_path).resolve()
            if candidate.is_file() and DIST_DIR.resolve() in candidate.parents:
                # python:slim lacks a few font/manifest MIME types.
                media = {".woff2": "font/woff2", ".woff": "font/woff", ".webmanifest": "application/manifest+json"}.get(candidate.suffix)
                return FileResponse(candidate, media_type=media, headers={"Cache-Control": "public, max-age=86400"})
        return FileResponse(
            DIST_DIR / "index.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
