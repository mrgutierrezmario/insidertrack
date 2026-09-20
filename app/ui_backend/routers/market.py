import logging
import random
import time as _time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from routers.access import require_admin
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.politician import Politician as PoliticianModel
from models.trade import Trade
from services.market_data import (
    AV_BASE,
    _cache_get,
    _cache_set,
    get_intraday,
    get_price_history,
    get_ticker_info,
    has_intraday,
)

try:
    import httpx
except ImportError:
    httpx = None

router = APIRouter(prefix="/market", tags=["market"])

VALID_INTERVALS = {"1min", "5min", "15min", "30min", "60min"}


@router.get("/intraday/{ticker}")
def intraday(
    ticker: str,
    interval: str = Query(default="1min", description="1min | 5min | 15min | 30min | 60min"),
):
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {VALID_INTERVALS}")
    if not has_intraday():
        raise HTTPException(
            status_code=503,
            detail="No Alpha Vantage key configured. Add ALPHA_VANTAGE_KEY to .env to enable intraday data.",
        )
    candles = get_intraday(ticker.upper(), interval)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No intraday data returned for {ticker}.")
    return {"ticker": ticker.upper(), "interval": interval, "candles": candles}


@router.get("/history/{ticker}")
def history(ticker: str, days: int = Query(default=90, ge=1, le=365)):
    candles = get_price_history(ticker.upper(), days)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No history returned for {ticker}.")
    return {"ticker": ticker.upper(), "days": days, "candles": candles}


@router.get("/info/{ticker}")
def ticker_info(ticker: str):
    return get_ticker_info(ticker.upper())


@router.get("/performance")
def performance(db: Session = Depends(get_db)):
    """30-day close prices for all tracked politicians' tickers."""
    rows = (
        db.query(Trade.ticker)
        .join(PoliticianModel, Trade.politician_id == PoliticianModel.id)
        .filter(PoliticianModel.is_tracked == True)  # noqa: E712
        .distinct()
        .all()
    )
    tickers = [r[0] for r in rows][:10]
    result = {}
    for ticker in tickers:
        history = get_price_history(ticker, days=30)
        if history:
            result[ticker] = [{"date": h["date"], "close": h["close"]} for h in history]
    return result


@router.get("/movers")
def market_movers(db: Session = Depends(get_db)):
    """Top gainers/losers/most-active from tracked ticker price history (no premium API needed)."""
    # Day-scoped cache key — close prices change at most once per day, so reusing
    # within the same UTC date is correct. Stale entries from prior days never
    # serve.
    cache_key = f"movers:{date.today().isoformat()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Movers from the signal universe (tickers traded in the last 45 days —
    # ~150, not the ~2,000 ever traded) using the same 60-day history the
    # signal warm-up already cached, fetched in parallel. The old version
    # walked every ticker ever traded with an uncached 5-day request and
    # took 40 s+ — and timed out before it could fill the day cache.
    cutoff = date.today() - timedelta(days=45)
    rows = (
        db.query(Trade.ticker)
        .join(PoliticianModel, Trade.politician_id == PoliticianModel.id)
        .filter(PoliticianModel.is_tracked == True, Trade.trade_date >= cutoff)  # noqa: E712
        .distinct()
        .all()
    )
    tickers = sorted({r[0] for r in rows if r[0]})

    def fetch(tk):
        try:
            return tk, get_price_history(tk, days=60)
        except Exception:
            return tk, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        histories = dict(pool.map(fetch, tickers))

    movers = []
    for ticker in tickers:
        try:
            hist = histories.get(ticker) or []
            if hist and hist[-1].get("_demo"):
                continue
            if len(hist) >= 2:
                prev = hist[-2]["close"]
                curr = hist[-1]["close"]
                if prev and prev > 0:
                    chg_pct = (curr - prev) / prev * 100
                    movers.append({
                        "ticker": ticker,
                        "price": round(curr, 2),
                        "change_amount": round(curr - prev, 2),
                        "change_percentage": f"{chg_pct:+.2f}%",
                        "volume": "—",
                    })
        except Exception:
            continue

    if movers:
        def pct(m): return float(m["change_percentage"].replace("%", "").replace("+", ""))
        gainers = sorted([m for m in movers if pct(m) > 0], key=pct, reverse=True)[:8]
        losers  = sorted([m for m in movers if pct(m) < 0], key=pct)[:8]
        active  = sorted(movers, key=pct, reverse=True)[:8]
        result = {"top_gainers": gainers, "top_losers": losers, "most_actively_traded": active, "_demo": False}
        _cache_set(cache_key, result, ttl=21_600)  # 6h — day-scoped key already prevents cross-day reuse
        return result

    # Demo fallback — only if no tracked tickers have price history
    rng = random.Random(hash(date.today().isoformat()))
    universe = [
        ("NVDA", 131), ("AAPL", 211), ("MSFT", 449), ("TSLA", 249), ("AMZN", 207),
        ("GOOG", 177), ("META", 614), ("AMD", 108), ("CRM", 309), ("ORCL", 192),
        ("SPY", 583), ("QQQ", 480), ("XOM", 117), ("CVX", 158), ("JPM", 238),
        ("BAC", 44), ("LMT", 467), ("RTX", 128), ("PLTR", 28), ("ARM", 142),
    ]
    movers = []
    for ticker, base in universe:
        change_pct = rng.uniform(-7, 7)
        price = base * (1 + change_pct / 100)
        movers.append({
            "ticker": ticker,
            "price": round(price, 2),
            "change_amount": round(base * change_pct / 100, 2),
            "change_percentage": f"{change_pct:+.2f}%",
            "volume": str(rng.randint(5_000_000, 80_000_000)),
        })

    def pct(m): return float(m["change_percentage"].replace("%", "").replace("+", ""))
    gainers = sorted([m for m in movers if pct(m) > 0], key=pct, reverse=True)[:8]
    losers  = sorted([m for m in movers if pct(m) < 0], key=pct)[:8]
    active  = sorted(movers, key=lambda m: int(m["volume"]), reverse=True)[:8]

    result = {"top_gainers": gainers, "top_losers": losers, "most_actively_traded": active, "_demo": True}
    _cache_set(cache_key, result, ttl=21_600)  # 6h — same as real-data path
    return result


@router.get("/status")
def market_status():
    from config import settings
    has_av = bool(settings.alpha_vantage_key)
    return {
        "intraday_enabled": True,  # keyless Yahoo fallback always available
        "intraday_source": "Alpha Vantage + Yahoo fallback" if has_av else "Yahoo Finance",
        "history_source": "Yahoo Finance",
        "note": "Intraday via Alpha Vantage (1-min, 25 req/day) with a keyless Yahoo fallback; results cached 5 min."
        if has_av
        else "Intraday via Yahoo Finance (keyless). Add ALPHA_VANTAGE_KEY for 1-min granularity.",
    }


@router.post("/warm-history")
def warm_history(background_tasks: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Pre-fetch daily price history for tracked tickers (slow — runs in background)."""
    from services.market_data import warm_price_history
    rows = (
        db.query(Trade.ticker)
        .join(PoliticianModel)
        .filter(PoliticianModel.is_tracked == True)  # noqa: E712
        .distinct()
        .all()
    )
    tickers = sorted({r[0] for r in rows if r[0]})
    background_tasks.add_task(warm_price_history, tickers)
    return {"status": "warming started", "tickers": len(tickers)}


_FED_RATE_CACHE: dict = {}
_FED_RATE_TTL = 6 * 3600  # 6 hours — rate changes at most 8×/year


def _fetch_fed_rate() -> dict:
    """Fetch Fed funds target upper bound from FRED public CSV (no API key needed)."""
    cached = _FED_RATE_CACHE.get("v")
    if cached and (_time.time() - cached["_ts"]) < _FED_RATE_TTL:
        return {k: v for k, v in cached.items() if k != "_ts"}

    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
        req = urllib.request.Request(url, headers={"User-Agent": "InsiderTrack/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            lines = resp.read().decode("utf-8").strip().splitlines()
        data_lines = [l for l in lines if l and not l.startswith("DATE")]
        if data_lines:
            date_str, val_str = data_lines[-1].strip().split(",")
            rate = float(val_str)
            result = {
                "label": "Fed Funds Rate",
                "type": "rate",
                "price": rate,
                "change_pct": 0.0,
                "as_of": date_str,
                "_stale": False,
            }
            _FED_RATE_CACHE["v"] = {**result, "_ts": _time.time()}
            return result
    except Exception:
        pass

    # Stale cache is better than nothing
    if cached:
        return {**{k: v for k, v in cached.items() if k != "_ts"}, "_stale": True}

    # Last-resort hardcoded fallback (updated 2026-05)
    return {
        "label": "Fed Funds Rate",
        "type": "rate",
        "price": 4.50,
        "change_pct": 0.0,
        "as_of": None,
        "_stale": True,
    }


@router.get("/macro")
def macro_indicators():
    """
    Key macro indicators: SPY, QQQ, VIX, TLT (10Y proxy), current Fed funds target.
    Uses yfinance for price data — same free source as price history.
    """
    # Day-scoped cache key — macro snapshots change at most once per trading day.
    # FRED Fed funds rate has its own 6-hour TTL on top.
    cache_key = f"macro:{date.today().isoformat()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    tickers_map = {
        "SPY":  {"label": "S&P 500",    "type": "index"},
        "QQQ":  {"label": "NASDAQ 100", "type": "index"},
        "^VIX": {"label": "VIX",        "type": "volatility"},
        "TLT":  {"label": "20Y Treasury (TLT)", "type": "rates"},
        "^TNX": {"label": "10Y Yield",  "type": "rates"},
        "GLD":  {"label": "Gold",       "type": "commodity"},
    }

    result = {}
    try:
        import yfinance as yf
        for sym, meta in tickers_map.items():
            try:
                hist = yf.Ticker(sym).history(period="5d", auto_adjust=True, timeout=20)
                if len(hist) >= 2:
                    curr = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2])
                    chg = (curr - prev) / prev * 100
                    result[sym] = {
                        **meta,
                        "price": round(curr, 2),
                        "change_pct": round(chg, 2),
                    }
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Macro fetch failed: {e}")

    result["FED_RATE"] = _fetch_fed_rate()

    # Only cache when we got meaningful index data alongside FED_RATE.
    # Long TTL is safe — day-scoped cache key already prevents cross-day reuse.
    if len(result) > 1:
        _cache_set(cache_key, result, ttl=21_600)  # 6h
    return result
