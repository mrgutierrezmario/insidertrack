"""
Stock price data.

- Current price + daily history: yfinance (free, no key needed)
- Intraday minute-by-minute: Alpha Vantage (requires ALPHA_VANTAGE_KEY in .env)

Alpha Vantage free tier = 25 requests/day, 5/minute.
Intraday results are cached in memory for 5 minutes to avoid burning the quota.
"""

import logging
import random
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import yfinance as yf

from config import settings

logger = logging.getLogger(__name__)

# yfinance logs every blocked request as an ERROR ("possibly delisted", crumb
# failures). Those are expected here — we fall through to the Yahoo chart
# endpoint — so silence its logger to keep our logs readable.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

AV_BASE = "https://www.alphavantage.co/query"

# Yahoo's public chart JSON endpoint. yfinance wraps this but adds a
# cookie/crumb handshake that gets blocked from many cloud IPs (the source of
# the constant "possibly delisted" failures); hitting the endpoint directly
# with a browser User-Agent is free, keyless, and far more reliable.
YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
_YAHOO_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Simple in-memory cache: { cache_key: (timestamp, data, ttl) }
_cache: dict[str, tuple[float, any, int]] = {}
CACHE_TTL = 300  # 5 minutes — default for intraday/short-window data


def _yahoo_chart(ticker: str, range_: str = "1y", interval: str = "1d") -> Optional[dict]:
    """Fetch and return the parsed `chart.result[0]` for a ticker, or None.

    Contains `meta` (incl. regularMarketPrice), `timestamp[]`, and
    `indicators.quote[0]` with open/high/low/close/volume arrays.
    """
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _YAHOO_UA}) as client:
            r = client.get(
                f"{YAHOO_CHART_BASE}{ticker}",
                params={"range": range_, "interval": interval},
            )
            r.raise_for_status()
            results = (r.json().get("chart") or {}).get("result") or []
            return results[0] if results else None
    except Exception as e:
        logger.warning(f"Yahoo chart failed for {ticker}: {e}")
        return None


def _yahoo_price(ticker: str) -> Optional[float]:
    result = _yahoo_chart(ticker, range_="1d", interval="1d")
    if not result:
        return None
    price = (result.get("meta") or {}).get("regularMarketPrice")
    return round(float(price), 2) if price else None


def _yahoo_history(ticker: str, days: int) -> Optional[list[dict]]:
    # Pick the smallest standard range that covers the requested window.
    range_ = "1mo" if days <= 30 else "3mo" if days <= 90 else "1y" if days <= 365 else "2y"
    result = _yahoo_chart(ticker, range_=range_, interval="1d")
    if not result:
        return None
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes, opens = quote.get("close") or [], quote.get("open") or []
    highs, lows, vols = quote.get("high") or [], quote.get("low") or [], quote.get("volume") or []
    cutoff = date.today() - timedelta(days=days)
    rows = []
    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        if c is None:  # Yahoo emits nulls for holidays/halts
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if d < cutoff:
            continue
        rows.append({
            "date": d.isoformat(),
            "open": round(opens[i], 2) if i < len(opens) and opens[i] is not None else round(c, 2),
            "high": round(highs[i], 2) if i < len(highs) and highs[i] is not None else round(c, 2),
            "low": round(lows[i], 2) if i < len(lows) and lows[i] is not None else round(c, 2),
            "close": round(c, 2),
            "volume": int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
        })
    rows.sort(key=lambda x: x["date"])
    return rows or None


# AV-style interval ("5min") → Yahoo interval ("5m").
_YAHOO_INTRADAY_INTERVAL = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m", "60min": "60m",
}


def _yahoo_intraday(ticker: str, interval: str) -> Optional[list[dict]]:
    """Today's intraday candles from Yahoo — keyless fallback for Alpha Vantage.

    Emits naive "YYYY-MM-DD HH:MM:SS" timestamps in the exchange's local time
    (via meta.gmtoffset), matching the Alpha Vantage shape the chart expects.
    """
    yint = _YAHOO_INTRADAY_INTERVAL.get(interval, "5m")
    result = _yahoo_chart(ticker, range_="1d", interval=yint)
    if not result:
        return None
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens, highs = quote.get("open") or [], quote.get("high") or []
    lows, closes, vols = quote.get("low") or [], quote.get("close") or [], quote.get("volume") or []
    offset = (result.get("meta") or {}).get("gmtoffset") or 0
    candles = []
    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        if c is None:  # Yahoo emits nulls for gaps within the session
            continue
        local = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(seconds=offset)
        candles.append({
            "time": local.strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(opens[i], 2) if i < len(opens) and opens[i] is not None else round(c, 2),
            "high": round(highs[i], 2) if i < len(highs) and highs[i] is not None else round(c, 2),
            "low": round(lows[i], 2) if i < len(lows) and lows[i] is not None else round(c, 2),
            "close": round(c, 2),
            "volume": int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
        })
    return candles or None


def _yf_call(fn, *args, retries: int = 1, backoff: float = 0.4, label: str = "yfinance", **kwargs):
    """
    Run a yfinance call with a small retry/backoff. yfinance has no native
    timeout, but transient HTTP failures (5xx, rate-limit blips, DNS hiccups)
    typically clear on a second attempt. After `retries` failures we re-raise
    so the caller can fall through to the next data source (Alpha Vantage or
    demo).
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            logger.debug(f"{label} failed after {retries + 1} attempts: {e}")
            raise
    raise last_exc  # unreachable, but quiets type-checkers


def _cache_get(key: str):
    """
    L1 (in-memory) → L2 (Postgres) lookup. On L2 hit, hydrate L1 with the
    remaining TTL so subsequent calls hit the fast path. See
    services/persistent_cache.py for the L2 implementation.
    """
    entry = _cache.get(key)
    if entry:
        ts, data, ttl = entry
        if (time.time() - ts) < ttl:
            return data
    # L1 miss → check L2
    from services.persistent_cache import cache_get as l2_get  # avoid import cycle
    l2 = l2_get(key)
    if l2 is None:
        return None
    value, remaining_ttl = l2
    _cache[key] = (time.time(), value, remaining_ttl)
    return value


def _cache_set(key: str, data, ttl: int = CACHE_TTL):
    """Cache `data` under `key` for `ttl` seconds (default 5 min). Writes both L1 and L2."""
    _cache[key] = (time.time(), data, ttl)
    if len(_cache) > 500:
        now = time.time()
        for k in [k for k, (ts, _d, t) in list(_cache.items()) if now - ts >= t]:
            del _cache[k]
    from services.persistent_cache import cache_set as l2_set  # avoid import cycle
    l2_set(key, data, ttl)


# ── Seed prices for demo fallback ────────────────────────────────────────────

_SEED_PRICES: dict[str, float] = {
    "AAPL": 211.0, "NVDA": 131.0, "MSFT": 449.0, "AMZN": 207.0,
    "GOOG": 177.0, "TSLA": 249.0, "CRM": 309.0, "META": 614.0,
    "LMT": 467.0, "RTX": 128.0, "BA": 177.0, "XOM": 117.0,
    "CVX": 158.0, "AMD": 108.0, "SPY": 583.0,
}


def _demo_history(ticker: str, days: int) -> list[dict]:
    """Synthetic price history used when yfinance is unavailable (dev/cloud env)."""
    base = _SEED_PRICES.get(ticker, 100.0)
    rng = random.Random(hash(ticker) % 100_000)
    result = []
    price = base * (1 - 0.06 * (days / 90))
    today = date.today()
    # Use a calendar buffer large enough to always yield at least `days` trading days
    buffer = days * 2 + 10
    for i in range(buffer):
        d = today - timedelta(days=buffer - 1 - i)
        if d.weekday() >= 5:
            continue
        change = rng.gauss(0.0005, 0.012)
        price = price * (1 + change)
        o = price * (1 + rng.gauss(0, 0.003))
        h = max(price, o) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(price, o) * (1 - abs(rng.gauss(0, 0.004)))
        result.append({
            "date": str(d),
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(lo, 2),
            "close": round(price, 2),
            "volume": rng.randint(5_000_000, 50_000_000),
            "_demo": True,
        })
    return result[-days:]


def _demo_price(ticker: str) -> float:
    return _SEED_PRICES.get(ticker, 100.0)


# ── Current price ─────────────────────────────────────────────────────────────

def get_current_price(ticker: str, with_meta: bool = False):
    """Returns the current price. If with_meta=True, returns {"price": float, "is_demo": bool}."""
    try:
        price = _yf_call(
            lambda: round(float(yf.Ticker(ticker).fast_info.last_price), 2),
            label=f"yfinance current_price[{ticker}]",
        )
        if price:
            return {"price": price, "is_demo": False} if with_meta else price
    except Exception:
        pass

    # Yahoo's chart endpoint directly — reliable where yfinance's crumb flow is blocked.
    yahoo = _yahoo_price(ticker)
    if yahoo:
        return {"price": yahoo, "is_demo": False} if with_meta else yahoo

    logger.warning(f"No live price source for {ticker}; using demo price")
    demo = _demo_price(ticker)
    return {"price": demo, "is_demo": True} if with_meta else demo


def get_bulk_prices(tickers: list[str]) -> dict[str, Optional[float]]:
    return {ticker: get_current_price(ticker) for ticker in tickers}


# ── Daily history cache (longer TTL — daily bars don't change intraday) ───────

HISTORY_CACHE_TTL = 86_400  # 24h — keeps Alpha Vantage within the 25 req/day free tier
_history_cache: dict[str, tuple[float, list]] = {}


def _history_cache_get(key: str):
    entry = _history_cache.get(key)
    if entry and (time.time() - entry[0]) < HISTORY_CACHE_TTL:
        return entry[1]
    # L1 miss → consult L2 (persistent_cache). Key is namespaced so it never
    # collides with the short-TTL _cache keys above.
    from services.persistent_cache import cache_get as l2_get
    l2 = l2_get(f"hist:{key}")
    if l2 is None:
        return None
    value, _remaining = l2
    _history_cache[key] = (time.time(), value)
    return value


def _history_cache_set(key: str, data: list):
    _history_cache[key] = (time.time(), data)
    if len(_history_cache) > 500:
        now = time.time()
        for k in [k for k, (ts, _) in list(_history_cache.items()) if now - ts >= HISTORY_CACHE_TTL]:
            del _history_cache[k]
    from services.persistent_cache import cache_set as l2_set  # avoid import cycle
    l2_set(f"hist:{key}", data, HISTORY_CACHE_TTL)


def _av_daily_history(ticker: str, days: int) -> Optional[list[dict]]:
    """Daily OHLC history via Alpha Vantage TIME_SERIES_DAILY (works from cloud IPs)."""
    if not settings.alpha_vantage_key:
        return None
    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(AV_BASE, params={
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker,
                "outputsize": "compact" if days <= 100 else "full",
                "apikey": settings.alpha_vantage_key,
            })
            r.raise_for_status()
            data = r.json()
        if "Note" in data or "Information" in data:
            logger.warning("Alpha Vantage daily-history limit/issue for %s", ticker)
            return None
        series = data.get("Time Series (Daily)", {})
        if not series:
            return None
        cutoff = date.today() - timedelta(days=days)
        rows = []
        for ds, v in series.items():
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            if d < cutoff:
                continue
            rows.append({
                "date": ds,
                "open": round(float(v["1. open"]), 2),
                "high": round(float(v["2. high"]), 2),
                "low": round(float(v["3. low"]), 2),
                "close": round(float(v["4. close"]), 2),
                "volume": int(v["5. volume"]),
            })
        rows.sort(key=lambda x: x["date"])
        return rows or None
    except Exception as e:
        logger.warning(f"Alpha Vantage daily history failed for {ticker}: {e}")
        return None


# ── Daily history (yfinance) ───────────────────────────────────────────────────

def get_price_history(ticker: str, days: int = 90) -> list[dict]:
    """Daily OHLC history. Tries yfinance, then Alpha Vantage, then demo data."""
    cache_key = f"history:{ticker}:{days}"
    cached = _history_cache_get(cache_key)
    if cached is not None:
        return cached

    # 1) yfinance (free, no key — but blocked from some cloud IPs)
    try:
        end = date.today()
        start = end - timedelta(days=days)
        hist = _yf_call(
            # timeout: one hung socket must not stall a thread pool (skill refresh, signals).
            lambda: yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(), timeout=20),
            label=f"yfinance history[{ticker}]",
        )
        # The chart-JSON paths above skip Yahoo's nulls for holidays and
        # halts; pandas carries those same gaps as NaN instead, and
        # round(nan, 2) is nan. One such row then poisons closes[-1] (a
        # ticker's current_price), every SMA computed over it, and any
        # attempt to cache the series — Postgres rejects NaN in a `json`
        # column, so the L2 write fails and the ticker is re-fetched on
        # every request. Skip them here, once, rather than in each caller.
        rows = [
            {
                "date": str(idx.date()),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
            for idx, row in hist.iterrows()
            if row[["Open", "High", "Low", "Close", "Volume"]].notna().all()
        ]
        if rows:
            _history_cache_set(cache_key, rows)
            return rows
    except Exception as e:
        logger.warning(f"yfinance failed for {ticker}: {e}")

    # 2) Yahoo chart endpoint directly — free, keyless, no quota; primary
    #    fallback since yfinance's crumb handshake is blocked from many IPs.
    yahoo_rows = _yahoo_history(ticker, days)
    if yahoo_rows:
        _history_cache_set(cache_key, yahoo_rows)
        return yahoo_rows

    # 3) Alpha Vantage daily history (cached 24h to respect the 25 req/day quota)
    av_rows = _av_daily_history(ticker, days)
    if av_rows:
        logger.info(f"Using Alpha Vantage daily history for {ticker}")
        _history_cache_set(cache_key, av_rows)
        return av_rows

    # 4) Synthetic demo fallback (not cached long — so a real source can take over)
    logger.info(f"Falling back to demo history for {ticker}")
    return _demo_history(ticker, days)


# ── Intraday (Alpha Vantage) ───────────────────────────────────────────────────

def _av_intraday_request(ticker: str, interval: str, outputsize: str) -> Optional[dict]:
    """One raw Alpha Vantage TIME_SERIES_INTRADAY call."""
    if not settings.alpha_vantage_key:
        return None
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(AV_BASE, params={
                "function": "TIME_SERIES_INTRADAY",
                "symbol": ticker,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": settings.alpha_vantage_key,
            })
            r.raise_for_status()
            data = r.json()
            if "Note" in data:
                logger.warning("Alpha Vantage rate limit hit: %s", data["Note"])
                return None
            if "Information" in data:
                logger.warning("Alpha Vantage key issue: %s", data["Information"])
                return None
            return data
    except Exception as e:
        logger.warning(f"Alpha Vantage request failed for {ticker}: {e}")
        return None


def get_intraday(ticker: str, interval: str = "1min") -> list[dict]:
    """
    Returns minute-by-minute candles for today's session.
    Falls back to an empty list if no AV key is configured.
    interval: "1min" | "5min" | "15min" | "30min" | "60min"
    """
    cache_key = f"intraday:{ticker}:{interval}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Alpha Vantage first (true 1-min granularity) when a key is configured and
    # within quota; otherwise fall back to Yahoo's keyless intraday.
    data = _av_intraday_request(ticker, interval, outputsize="compact")
    if data:
        series = data.get(f"Time Series ({interval})", {})
        candles = sorted(
            [
                {
                    "time": ts,
                    "open": float(v["1. open"]),
                    "high": float(v["2. high"]),
                    "low": float(v["3. low"]),
                    "close": float(v["4. close"]),
                    "volume": int(v["5. volume"]),
                }
                for ts, v in series.items()
            ],
            key=lambda c: c["time"],
        )
        if candles:
            _cache_set(cache_key, candles)
            logger.info(f"Fetched {len(candles)} intraday candles for {ticker} (AV {interval})")
            return candles

    yahoo = _yahoo_intraday(ticker, interval)
    if yahoo:
        _cache_set(cache_key, yahoo)
        logger.info(f"Fetched {len(yahoo)} intraday candles for {ticker} (Yahoo {interval})")
        return yahoo

    return []


def has_intraday() -> bool:
    """Intraday is always available now via the keyless Yahoo fallback (Alpha
    Vantage is used first when a key is configured and within quota)."""
    return True


# ── Ticker info ───────────────────────────────────────────────────────────────

_ticker_info_cache: dict[str, dict] = {}


def get_ticker_info(ticker: str) -> dict:
    try:
        info = _yf_call(lambda: yf.Ticker(ticker).info, label=f"yfinance info[{ticker}]")
        result = {
            "ticker": ticker,
            "name": info.get("longName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "description": info.get("longBusinessSummary", "")[:500],
        }
        _ticker_info_cache[ticker] = result
        return result
    except Exception as e:
        logger.debug(f"yfinance info unavailable for {ticker}: {e}")

    if ticker in _ticker_info_cache:
        return {**_ticker_info_cache[ticker], "_stale": True}

    # Partial fallback: Yahoo's chart meta has price-derived fields (52w range)
    # even when the crumb-gated fundamentals (name/sector/P-E) are blocked.
    meta = (_yahoo_chart(ticker, range_="1d", interval="1d") or {}).get("meta") or {}
    return {
        "ticker": ticker,
        "name": "",
        "sector": "",
        "industry": "",
        "market_cap": None,
        "pe_ratio": None,
        "52w_high": meta.get("fiftyTwoWeekHigh"),
        "52w_low": meta.get("fiftyTwoWeekLow"),
        "description": "",
    }


# ── Cache warming ─────────────────────────────────────────────────────────────

def warm_price_history(tickers: list[str], days: int = 90, delay: float = 15.0) -> dict:
    """
    Pre-fetch daily history for many tickers slowly, staying under Alpha
    Vantage's 5-calls-per-minute free-tier limit. Successful fetches land in
    the 24h history cache so later signal requests never make live API calls.
    Intended to be run once daily by the scheduler.
    """
    warmed = 0
    demo = 0
    for i, ticker in enumerate(tickers):
        rows = get_price_history(ticker, days)
        if rows and not (rows[0].get("_demo")):
            warmed += 1
        else:
            demo += 1
        if i < len(tickers) - 1:
            time.sleep(delay)
    logger.info(f"Price-history warm-up: {warmed} live, {demo} demo")
    return {"warmed": warmed, "demo": demo}
