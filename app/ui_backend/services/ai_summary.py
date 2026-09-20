"""
AI-generated research summaries.

Produces a plain-language bull case / bear case / risk note for a ticker,
grounded in the data the app already has (signal score, insider trades,
whale positions, news sentiment, earnings). The provider (Claude, Gemini or
OpenAI) is chosen in Settings — see services/providers.py. Results are cached
in memory because each call costs money.

Falls back gracefully when no API key is configured.
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from models.politician import Politician
from models.trade import Trade
from models.whale import WhaleHolder, WhalePosition

logger = logging.getLogger(__name__)

CACHE_TTL = 21_600  # 6 hours
_cache: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = (time.time(), data)


def _gather_context(ticker: str, db: Session) -> dict:
    """Pull the structured facts the model should reason over."""
    cutoff = date.today() - timedelta(days=90)

    trades = (
        db.query(Trade)
        .join(Politician)
        .filter(Politician.is_tracked == True, Trade.ticker == ticker, Trade.trade_date >= cutoff)  # noqa: E712
        .order_by(Trade.trade_date.desc())
        .limit(15)
        .all()
    )
    congress = [
        {
            "politician": t.politician.name if t.politician else "Unknown",
            "type": t.transaction_type,
            "asset": t.asset_type or "stock",
            "direction": t.direction,
            "owner": t.owner,
            "amount": t.amount_range,
            "date": str(t.trade_date),
        }
        for t in trades
    ]

    positions = (
        db.query(WhalePosition)
        .join(WhaleHolder)
        .filter(WhaleHolder.is_tracked == True, WhalePosition.ticker == ticker)  # noqa: E712
        .order_by(WhalePosition.filing_date.desc())
        .limit(10)
        .all()
    )
    whales = [
        {
            "holder": p.holder.name if p.holder else "Unknown",
            "change": p.change_type,
            "quarter": p.quarter,
        }
        for p in positions
    ]

    # Signal score
    signal = None
    try:
        from routers.signals import technical_signals
        for s in technical_signals(db).get("signals", []):
            if s.get("ticker") == ticker:
                signal = {
                    "composite_score": s.get("composite_score"),
                    "label": s.get("label"),
                    "sub_scores": s.get("sub_scores"),
                    "rsi": s.get("rsi"),
                    "current_price": s.get("current_price"),
                }
                break
    except Exception as e:
        logger.warning(f"Could not load signal for AI context: {e}")

    return {"ticker": ticker, "signal": signal, "congress_trades": congress, "whale_positions": whales}


# ── Daily spend cap for the site's own keys ────────────────────────────────────
# Per-IP throttling and the 6h cache bound *one* visitor; they do nothing
# about many visitors (or a crawler) walking every ticker. Cap fresh
# generations paid for by the site at AI_DAILY_CAP per UTC day. Visitor keys
# are their own money and are not counted. In-memory: a restart resets it,
# which errs on the side of serving notes.
_daily = {"day": None, "count": 0}


def _site_budget_ok() -> bool:
    from config import settings
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _daily["day"] != today:
        _daily.update(day=today, count=0)
    return _daily["count"] < settings.ai_daily_cap


def _site_budget_spend() -> None:
    _daily["count"] += 1


def _over_budget(ticker: str, context: dict) -> dict:
    return {
        "ticker": ticker,
        "available": False,
        "message": "This site's AI research budget for today is used up. Notes resume tomorrow, or add your own key under Settings → AI research notes.",
        "context": context,
    }


def _fallback(ticker: str, context: dict) -> dict:
    return {
        "ticker": ticker,
        "available": False,
        "message": "No AI provider is set up for this site. Add your own Claude, Gemini or OpenAI key under Settings → AI research notes.",
        "context": context,
    }


def generate_stock_summary(ticker: str, db: Session, force: bool = False, cred=None) -> dict:
    """``cred`` is a visitor's own provider key (services.providers.Credential);
    without it the site's configured provider is used."""
    from services.providers import ProviderError, active_provider, generate_text, model_for

    ticker = ticker.upper()
    # Notes differ by who wrote them, so cache per provider/model. A note paid
    # for by a visitor's key is public data like everything else here and is
    # served from the same cache.
    if cred is not None:
        cache_key = f"summary:{ticker}:{cred.provider}:{cred.model or model_for(cred.provider)}"
    else:
        active = active_provider()
        cache_key = f"summary:{ticker}:{active}:{model_for(active) if active else ''}"
    if not force:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    context = _gather_context(ticker, db)

    if cred is None and active_provider() is None:
        return _fallback(ticker, context)
    if cred is None and not _site_budget_ok():
        logger.warning(f"AI daily cap reached — not generating note for {ticker}")
        return _over_budget(ticker, context)

    prompt = f"""You are a careful investment research assistant. Using ONLY the data below, write a brief, balanced research note for the stock {ticker}.

DATA:
{context}

Write a JSON object with exactly these keys:
- "why_today": one sentence on why this stock is worth a look right now, based on the data
- "bull_case": 2-3 sentences making the optimistic case
- "bear_case": 2-3 sentences making the cautious case
- "risk_note": one sentence flagging the single biggest risk or data limitation

Rules: Never say a trade is guaranteed. Never tell the user to buy or sell. Note that congressional and 13F data is delayed/lagging. Be factual and concise. Output ONLY the raw JSON object, no markdown fencing."""

    try:
        if cred is None:
            _site_budget_spend()
        gen = generate_text(prompt, max_tokens=700, timeout=45.0, cred=cred, job="notes")
        text = gen.text
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()

        import json
        parsed = json.loads(text)
        result = {
            "ticker": ticker,
            "available": True,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": gen.provider,
            "source": "own" if cred is not None else "site",
            "fallback": gen.fallback,
            "fallback_reason": gen.fallback_reason,
            **{k: parsed.get(k, "") for k in ("why_today", "bull_case", "bear_case", "risk_note")},
            "context": context,
        }
        _cache_set(cache_key, result)
        logger.info(f"Generated AI summary for {ticker} via {gen.provider}")
        return result
    except Exception as e:
        logger.warning(f"AI summary generation failed for {ticker}: {e}")
        return {
            "ticker": ticker,
            "available": False,
            "message": f"Could not generate AI summary: {e}" if not isinstance(e, ProviderError) else f"Could not generate AI summary — {e}",
            "context": context,
        }
