"""
The model desk: once a morning the site's AI provider reads that day's
disclosure data and makes 3–5 directional calls — which are then measured
exactly the way members' trades are (price at the call → price at the
horizon, against SPY) and shown with a running hit-rate.

The point is accountability, not prediction. A language model has no
information the page doesn't already show; what it can do is reason over
today's data out loud, and what we can do is keep score. If it turns out to
be a coin flip, the page says so.

One model call per day on the site's keys; nothing here is advice.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.model_call import ModelBrief, ModelCall
from services.market_data import get_price_history
from services.track_record import _close_on_or_after, _close_on_or_before, _pct

logger = logging.getLogger(__name__)

HORIZONS = (30, 60, 90)
MIN_CALLS, MAX_CALLS = 3, 5

PROMPT = """You are the research desk for InsiderTrack, a site that tracks the stock trades U.S. legislators, corporate insiders and large funds are legally required to disclose. Below is TODAY's data. Read it and make {min_calls}–{max_calls} directional calls on specific tickers that appear in the data.

For each call give:
- "ticker": the symbol, exactly as it appears in the data
- "direction": "bullish" or "bearish"
- "horizon_days": 30, 60 or 90
- "confidence": 0 to 1
- "reasoning": two sentences, citing the specific evidence in the data (who bought/sold, how much, their track record, the insider cluster, the score). No generalities.
Also write "summary": three sentences on what stands out in today's data overall.

Rules: only tickers present in the data; prefer evidence from several sources agreeing (a member with a strong track record buying, plus corporate insiders buying, plus a rising score). Bearish calls are welcome when the evidence points that way. Never mention that you cannot predict markets — you are making calls precisely so they can be scored. Return ONLY a JSON object: {{"summary": "...", "calls": [ ... ]}}

TODAY'S DATA:
{context}"""


# ── Context ──────────────────────────────────────────────────────────────────

def build_context(db: Session, day: date) -> dict:
    """The compact picture of the last few days the model reasons over."""
    from models.insider import Form4Transaction
    from models.politician import Politician
    from models.trade import Trade
    from routers.signals import technical_signals

    since = day - timedelta(days=3)
    # Congressional buys/sells disclosed recently, biggest first, with the member's record
    rows = (
        db.query(Trade, Politician)
        .join(Politician)
        .filter(Trade.disclosure_date >= since, Trade.direction.in_(["buy", "sell"]), Trade.asset_type == "stock",
               Politician.is_tracked == True)  # noqa: E712
        .order_by(Trade.amount_high.desc().nullslast())
        .limit(40)
        .all()
    )
    congress = [{
        "ticker": t.ticker, "side": t.direction, "member": p.name, "amount": t.amount_range,
        "trade_date": t.trade_date.isoformat(), "disclosed": t.disclosure_date.isoformat(),
        "member_beat_spy_90d_pct": p.skill_beat_spy, "member_measured_buys": p.skill_n,
    } for t, p in rows]

    # Insider cluster buys, last 14 days
    cutoff = day - timedelta(days=14)
    clusters = (
        db.query(Form4Transaction.ticker, func.count(func.distinct(Form4Transaction.insider_name)),
                 func.sum(Form4Transaction.value), func.max(Form4Transaction.transaction_date))
        .filter(Form4Transaction.transaction_type == "buy", Form4Transaction.transaction_date >= cutoff,
                Form4Transaction.ticker.isnot(None))
        .group_by(Form4Transaction.ticker)
        .having(func.count(func.distinct(Form4Transaction.insider_name)) >= 2)
        .order_by(func.sum(Form4Transaction.value).desc())
        .limit(15)
        .all()
    )
    insider_clusters = [{"ticker": t, "insiders_buying": int(n), "dollars": int(d or 0), "last_buy": l.isoformat() if l else None}
                        for t, n, d, l in clusters]

    # Top and bottom of the score
    sigs = technical_signals(db).get("signals", [])
    def slim(s):
        return {"ticker": s["ticker"], "score": s["composite_score"], "label": s["label"],
                "congress_buys": s.get("insider_buys"), "congress_sells": s.get("insider_sells"),
                "form4_buys": s.get("corporate_buys"), "form4_sells": s.get("corporate_sells"),
                "rsi": s.get("rsi"), "top_reason": (s.get("reasons") or [""])[0]}
    top = [slim(s) for s in sigs[:12]]
    bottom = [slim(s) for s in sigs[-8:]]

    return {"date": day.isoformat(), "congress_recent": congress, "insider_cluster_buys": insider_clusters,
            "top_scores": top, "bottom_scores": bottom}


# ── Generation ───────────────────────────────────────────────────────────────

def _parse(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None


def generate_brief(db: Session, day: Optional[date] = None, force: bool = False) -> dict:
    """Make today's brief and calls. Idempotent per day unless `force`."""
    from services.providers import ProviderError, active_provider, generate_text
    day = day or date.today()
    if active_provider() is None:
        return {"status": "no_provider"}
    if not force and db.query(ModelBrief).filter(ModelBrief.brief_date == day).first():
        return {"status": "exists", "date": day.isoformat()}

    context = build_context(db, day)
    known = {c["ticker"] for c in context["congress_recent"]} | {c["ticker"] for c in context["insider_cluster_buys"]} \
            | {s["ticker"] for s in context["top_scores"] + context["bottom_scores"]}
    prompt = PROMPT.format(min_calls=MIN_CALLS, max_calls=MAX_CALLS, context=json.dumps(context, separators=(",", ":")))
    try:
        gen = generate_text(prompt, max_tokens=1800, timeout=90.0)
    except ProviderError as exc:
        logger.warning(f"model desk: generation failed: {exc}")
        return {"status": "failed", "error": str(exc)}
    parsed = _parse(gen.text)
    if not parsed or not isinstance(parsed.get("calls"), list):
        logger.warning("model desk: no JSON in response")
        return {"status": "failed", "error": "model returned no JSON"}

    if force:
        db.query(ModelCall).filter(ModelCall.call_date == day).delete()
        db.query(ModelBrief).filter(ModelBrief.brief_date == day).delete()
    db.add(ModelBrief(brief_date=day, summary=(parsed.get("summary") or "").strip()[:2000], provider=gen.provider,
                      context_json=json.dumps(context)))

    stored, rejected = 0, []
    seen = set()
    for c in parsed["calls"][:MAX_CALLS]:
        tk = (c.get("ticker") or "").strip().upper()
        direction = (c.get("direction") or "").strip().lower()
        try:
            horizon = int(c.get("horizon_days") or 0)
        except (TypeError, ValueError):
            horizon = 0
        if tk not in known or direction not in ("bullish", "bearish") or horizon not in HORIZONS or tk in seen:
            rejected.append(tk or "?")
            continue
        hist = get_price_history(tk, days=30)
        if not hist or hist[-1].get("_demo"):
            rejected.append(tk)
            continue
        seen.add(tk)
        try:
            conf = max(0.0, min(1.0, float(c.get("confidence") or 0)))
        except (TypeError, ValueError):
            conf = None
        db.add(ModelCall(call_date=day, ticker=tk, direction=direction, horizon_days=horizon, confidence=conf,
                         reasoning=(c.get("reasoning") or "").strip()[:1000], provider=gen.provider,
                         price_at_call=float(hist[-1]["close"])))
        stored += 1
    db.commit()
    logger.info(f"model desk {day}: {stored} calls stored, rejected {rejected} via {gen.provider}")
    return {"status": "ok", "date": day.isoformat(), "calls": stored, "rejected": rejected, "provider": gen.provider}


# ── Resolution ───────────────────────────────────────────────────────────────

def resolve_calls(db: Session, today: Optional[date] = None) -> int:
    """Score every call whose horizon has passed. A hit means the direction
    was right *against SPY* over the horizon — the same bar the members'
    track records use."""
    today = today or date.today()
    due = db.query(ModelCall).filter(ModelCall.resolved_at.is_(None)).all()
    due = [c for c in due if c.call_date + timedelta(days=c.horizon_days) <= today]
    if not due:
        return 0
    span = max((today - c.call_date).days for c in due) + 10
    spy = get_price_history("SPY", days=span)
    if not spy or spy[-1].get("_demo"):
        logger.warning("model desk: no SPY history — cannot resolve")
        return 0
    n = 0
    for c in due:
        hist = get_price_history(c.ticker, days=span)
        if not hist or hist[-1].get("_demo"):
            continue
        entry = c.price_at_call or (_close_on_or_after(hist, c.call_date) or (None, None))[1]
        target = c.call_date + timedelta(days=c.horizon_days)
        exit_px = _close_on_or_before(hist, target)
        spy_entry = _close_on_or_after(spy, c.call_date)
        spy_exit = _close_on_or_before(spy, target)
        if not (entry and exit_px and spy_entry and spy_exit):
            continue
        r = _pct(entry, exit_px)
        s = _pct(spy_entry[1], spy_exit)
        x = round(r - s, 2)
        c.price_at_horizon = round(exit_px, 2)
        c.return_pct, c.spy_return_pct, c.excess_pct = r, s, x
        c.outcome = "hit" if ((c.direction == "bullish" and x > 0) or (c.direction == "bearish" and x < 0)) else "miss"
        c.resolved_at = datetime.now(timezone.utc)
        n += 1
    db.commit()
    logger.info(f"model desk: resolved {n} call(s)")
    return n


# ── Read side ────────────────────────────────────────────────────────────────

def _call_dict(c: ModelCall) -> dict:
    return {
        "id": c.id, "call_date": c.call_date.isoformat(), "ticker": c.ticker, "direction": c.direction,
        "horizon_days": c.horizon_days, "confidence": c.confidence, "reasoning": c.reasoning, "provider": c.provider,
        "price_at_call": c.price_at_call, "price_at_horizon": c.price_at_horizon, "return_pct": c.return_pct,
        "spy_return_pct": c.spy_return_pct, "excess_pct": c.excess_pct, "outcome": c.outcome,
        "resolves_on": (c.call_date + timedelta(days=c.horizon_days)).isoformat(),
    }


def stats(db: Session) -> dict:
    resolved = db.query(ModelCall).filter(ModelCall.resolved_at.isnot(None)).all()
    out = {"resolved": len(resolved), "pending": db.query(func.count(ModelCall.id)).filter(ModelCall.resolved_at.is_(None)).scalar() or 0,
           "hit_rate": None, "avg_excess": None, "by_horizon": {}, "by_direction": {}}
    if resolved:
        out["hit_rate"] = round(sum(1 for c in resolved if c.outcome == "hit") / len(resolved) * 100, 1)
        out["avg_excess"] = round(mean(c.excess_pct for c in resolved if c.excess_pct is not None), 2)
        for h in HORIZONS:
            rs = [c for c in resolved if c.horizon_days == h]
            if rs:
                out["by_horizon"][str(h)] = {"n": len(rs), "hit_rate": round(sum(1 for c in rs if c.outcome == "hit") / len(rs) * 100, 1),
                                             "avg_excess": round(mean(c.excess_pct for c in rs), 2)}
        for d in ("bullish", "bearish"):
            rs = [c for c in resolved if c.direction == d]
            if rs:
                out["by_direction"][d] = {"n": len(rs), "hit_rate": round(sum(1 for c in rs if c.outcome == "hit") / len(rs) * 100, 1)}
    return out


def today(db: Session) -> dict:
    brief = db.query(ModelBrief).order_by(ModelBrief.brief_date.desc()).first()
    if not brief:
        return {"brief": None, "calls": [], "stats": stats(db)}
    calls = db.query(ModelCall).filter(ModelCall.call_date == brief.brief_date).order_by(ModelCall.confidence.desc().nullslast()).all()
    return {"brief": {"date": brief.brief_date.isoformat(), "summary": brief.summary, "provider": brief.provider},
            "calls": [_call_dict(c) for c in calls], "stats": stats(db)}


def history(db: Session, limit: int = 200) -> list[dict]:
    rows = db.query(ModelCall).order_by(ModelCall.call_date.desc(), ModelCall.id.desc()).limit(limit).all()
    return [_call_dict(c) for c in rows]
