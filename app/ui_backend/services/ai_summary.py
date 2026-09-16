"""
AI-generated research summaries via the Anthropic Claude API.

Produces a plain-language bull case / bear case / risk note for a ticker,
grounded in the data the app already has (signal score, insider trades,
whale positions, news sentiment, earnings). Results are cached in memory
because each call costs money.

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

MODEL = "claude-sonnet-4-6"
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


def _fallback(ticker: str, context: dict) -> dict:
    return {
        "ticker": ticker,
        "available": False,
        "message": "AI summaries are not configured. Add an Anthropic API key in Settings to enable them.",
        "context": context,
    }


def generate_stock_summary(ticker: str, db: Session, force: bool = False) -> dict:
    ticker = ticker.upper()
    cache_key = f"summary:{ticker}"
    if not force:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    context = _gather_context(ticker, db)

    if not settings.anthropic_api_key:
        return _fallback(ticker, context)

    try:
        from anthropic import Anthropic
    except ImportError:
        logger.warning("anthropic package not installed")
        return _fallback(ticker, context)

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
        # Explicit timeout — the SDK default is 10 minutes, which would block
        # a uvicorn worker for the full duration if Anthropic is slow.
        client = Anthropic(api_key=settings.anthropic_api_key, timeout=30.0)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()

        import json
        parsed = json.loads(text)
        result = {
            "ticker": ticker,
            "available": True,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": MODEL,
            **{k: parsed.get(k, "") for k in ("why_today", "bull_case", "bear_case", "risk_note")},
            "context": context,
        }
        _cache_set(cache_key, result)
        logger.info(f"Generated AI summary for {ticker}")
        return result
    except Exception as e:
        logger.warning(f"AI summary generation failed for {ticker}: {e}")
        return {
            "ticker": ticker,
            "available": False,
            "message": f"Could not generate AI summary: {e}",
            "context": context,
        }
