"""
Technical + composite signal scores per ticker.

Composite score (0-100), SCORE_VERSION 2:
  Smart Money  (0-20): whale 13F position changes
  Congress     (0-30): congressional buy/sell conviction, dollar-weighted
  Corporate    (0-25): Form 4 open-market buys vs sells by company insiders
  Momentum     (0-25): SMA20/50 crossover + RSI
  Risk penalty (0-20): reduces score for HIGH-risk recent trades

The "insider" sub-score key is the congressional one (kept for the stored
snapshots); "corporate" is the Form 4 one. News sentiment was dropped in v2:
the Alpha Vantage free tier can't cover the ticker universe, so it returned
a constant neutral 5/10 for every ticker — 10% of the score doing nothing.

Bump SCORE_VERSION whenever weights or inputs change: snapshots record it so
the Outcomes hit-rates can be read per regime instead of blending them.

Labels:
  70-100 → Strong Watch
  50-69  → Watch
  30-49  → Neutral
  15-29  → High Risk
  0-14   → Avoid for Now
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.insider import Form4Transaction
from models.politician import Politician
from models.trade import Trade
from models.whale import WhaleHolder, WhalePosition
from services import trade_semantics as sem
from services.market_data import get_price_history

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signals", tags=["signals"])

# Module-level cache — all four callers (signals, watchlist, alert engine, AI summary)
# share one computed result per 5-minute window, eliminating redundant price-API fan-out.
_signals_cache: dict = {}
_SIGNALS_TTL = 300  # 5 minutes

# 1 = original weights (through 2026-09-19 AM): smart 30 / congress 25 /
#     momentum 25 / sentiment 10 / fundamentals stub 10.
# 2 = Form 4 added, dollar-weighted Congress, sentiment and stub removed.
SCORE_VERSION = 2


# ── Indicator math ─────────────────────────────────────────────────────────────

def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 2)


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


# ── Sub-score computations ────────────────────────────────────────────────────

def _momentum_score(closes: list[float]) -> tuple[int, list[str]]:
    """Returns (score_0_25, reasons). Based on SMA crossover + RSI."""
    if not closes:
        return 12, ["No price data"]

    current = closes[-1]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    rsi = _rsi(closes)

    score = 12  # start neutral
    reasons = []

    if sma20 and sma50:
        if sma20 > sma50:
            score += 5
            reasons.append("SMA20 above SMA50 (golden cross zone)")
        else:
            score -= 5
            reasons.append("SMA20 below SMA50 (death cross zone)")

    if current and sma20:
        if current > sma20:
            score += 4
            reasons.append(f"Price above SMA20 (${sma20})")
        else:
            score -= 4
            reasons.append(f"Price below SMA20 (${sma20})")

    if rsi is not None:
        if rsi < 30:
            score += 4
            reasons.append(f"RSI {rsi} — oversold, potential bounce")
        elif rsi > 70:
            score -= 4
            reasons.append(f"RSI {rsi} — overbought, potential pullback")
        else:
            reasons.append(f"RSI {rsi} — neutral range")

    return max(0, min(25, score)), reasons


# Midpoint assumed for a trade whose bracket could not be parsed — the
# smallest STOCK Act bracket ($1,001–$15,000), so unknowns never dominate.
_DEFAULT_TRADE_DOLLARS = 8_000


def _fmt_dollars(n: float) -> str:
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n:.0f}"


def _insider_score(buys: int, sells: int, buy_dollars: float = 0, sell_dollars: float = 0) -> tuple[int, list[str]]:
    """Congressional conviction, 0–30. The buy/sell split is weighted by the
    bracket midpoint so one $5M purchase outweighs five $1K ones; counts are
    only used when no dollar figures are known."""
    reasons = []
    if buys == 0 and sells == 0:
        return 15, ["No recent congressional activity"]

    if buy_dollars + sell_dollars > 0:
        buy_ratio = buy_dollars / (buy_dollars + sell_dollars)
        buy_txt = f"{buys} buy(s) ≈ {_fmt_dollars(buy_dollars)}"
        sell_txt = f"{sells} sell(s) ≈ {_fmt_dollars(sell_dollars)}"
    else:
        buy_ratio = buys / (buys + sells)
        buy_txt, sell_txt = f"{buys} buy(s)", f"{sells} sell(s)"

    if buy_ratio >= 1.0:
        score = 30
        reasons.append(f"Congress: {buy_txt}, no recent sells — strong conviction")
    elif buy_ratio >= 0.7:
        score = 24
        reasons.append(f"Congress: {buy_txt} vs {sell_txt} — bullish lean")
    elif buy_ratio >= 0.4:
        score = 15
        reasons.append(f"Congress: mixed — {buy_txt}, {sell_txt}")
    elif buy_ratio > 0:
        score = 7
        reasons.append(f"Congress: {sell_txt} outweigh {buy_txt}")
    else:
        score = 0
        reasons.append(f"Congress: {sell_txt}, no recent buys — bearish signal")

    return score, reasons


def _corporate_score(txns: list) -> tuple[int, list[str]]:
    """Form 4 conviction, 0–25, from open-market buys (P) and sells (S) by the
    company's own officers, directors and 10% owners, weighted by dollar
    value. Insider *buying* is the informative side — executives sell for
    liquidity, taxes and 10b5-1 plans — so all-sells is discounted, and a
    cluster of distinct insiders buying earns a bonus."""
    if not txns:
        return 12, ["No Form 4 insider activity"]

    buy_val = sum((t.value or 0) for t in txns if t.transaction_type == "buy")
    sell_val = sum((t.value or 0) for t in txns if t.transaction_type == "sell")
    buys = [t for t in txns if t.transaction_type == "buy"]
    sells = [t for t in txns if t.transaction_type == "sell"]
    if not buys and not sells:
        return 12, ["Form 4 filings are grants/exercises only — no open-market trades"]

    total = buy_val + sell_val
    buy_ratio = buy_val / total if total else len(buys) / (len(buys) + len(sells))
    buyers = {t.insider_name for t in buys if t.insider_name}
    buy_txt = f"{len(buys)} insider buy(s) ≈ {_fmt_dollars(buy_val)}"
    sell_txt = f"{len(sells)} insider sale(s) ≈ {_fmt_dollars(sell_val)}"

    reasons = []
    if buy_ratio >= 1.0:
        score = 22
        reasons.append(f"Form 4: {buy_txt}, no open-market sells")
    elif buy_ratio >= 0.7:
        score = 18
        reasons.append(f"Form 4: {buy_txt} vs {sell_txt} — insiders net buyers")
    elif buy_ratio >= 0.4:
        score = 12
        reasons.append(f"Form 4: mixed — {buy_txt}, {sell_txt}")
    elif buy_ratio > 0:
        score = 7
        reasons.append(f"Form 4: {sell_txt} outweigh {buy_txt}")
    else:
        score = 4
        reasons.append(f"Form 4: {sell_txt}, no buys (insider selling is often routine)")

    if len(buyers) >= 2:
        score = min(25, score + 3)
        reasons.append(f"Cluster buy: {len(buyers)} different insiders bought")
    return score, reasons


def _smart_money_from_positions(positions: list) -> tuple[int, list[str]]:
    """Score from a pre-fetched list of WhalePosition objects for one ticker."""
    if not positions:
        return 10, ["No institutional 13F data for this ticker"]

    change_scores = {"new": 20, "increased": 15, "stable": 10, "decreased": 5, "closed": 0}
    scores = [change_scores.get(p.change_type or "stable", 10) for p in positions]
    avg = round(sum(scores) / len(scores))

    latest = positions[0]
    holder_names = list({p.holder.name.split(" (")[0] for p in positions if p.holder})
    reasons = [f"{', '.join(holder_names[:3])} hold this position"]
    if latest.change_type == "new":
        reasons.append("New position opened by institutional holder")
    elif latest.change_type == "increased":
        reasons.append("Institution increased position this quarter")
    elif latest.change_type == "decreased":
        reasons.append("Institution reduced position this quarter")
    elif latest.change_type == "closed":
        reasons.append("Institution closed position this quarter")
    return avg, reasons


def _smart_money_score(ticker: str, db: Session) -> tuple[int, list[str]]:
    """Single-ticker DB query version — for callers that don't pre-fetch."""
    positions = (
        db.query(WhalePosition)
        .join(WhaleHolder)
        .filter(WhaleHolder.is_tracked == True, WhalePosition.ticker == ticker)  # noqa: E712
        .order_by(WhalePosition.filing_date.desc())
        .limit(10)
        .all()
    )
    return _smart_money_from_positions(positions)


def _risk_penalty_from_trades(recent_trades: list) -> tuple[int, list[str]]:
    """Penalty from a pre-fetched list of Trade objects for one ticker."""
    from routers.trades import _risk_level
    if not recent_trades:
        return 0, []
    high_count = sum(1 for t in recent_trades if _risk_level(t) == "HIGH")
    medium_count = sum(1 for t in recent_trades if _risk_level(t) == "MEDIUM")
    penalty = min(20, high_count * 5 + medium_count * 2)
    reasons = []
    if high_count:
        reasons.append(f"{high_count} HIGH-risk disclosure(s) — stale data")
    if medium_count:
        reasons.append(f"{medium_count} MEDIUM-risk disclosure(s)")
    return penalty, reasons


def _risk_penalty(ticker: str, db: Session) -> tuple[int, list[str]]:
    """Single-ticker DB query version — for callers that don't pre-fetch."""
    cutoff = date.today() - timedelta(days=45)
    recent_trades = (
        db.query(Trade)
        .join(Politician)
        .filter(
            Politician.is_tracked == True,  # noqa: E712
            Trade.ticker == ticker,
            Trade.trade_date >= cutoff,
        )
        .all()
    )
    return _risk_penalty_from_trades(recent_trades)


def _composite_label(score: int) -> str:
    if score >= 70:
        return "Strong Watch"
    if score >= 50:
        return "Watch"
    if score >= 30:
        return "Neutral"
    if score >= 15:
        return "High Risk"
    return "Avoid for Now"


def _bullish_label(score: int) -> str:
    if score >= 2:
        return "BULLISH"
    if score <= -2:
        return "BEARISH"
    return "NEUTRAL"


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/")
def technical_signals(db: Session = Depends(get_db)):
    """
    Full composite signal scores for all tickers traded by tracked politicians.
    Results are cached for 5 minutes and shared across all internal callers
    (watchlist, alert engine, AI summary) to avoid redundant price-API fan-out.
    """
    cached = _signals_cache.get("v")
    if cached and (time.time() - cached["_ts"]) < _SIGNALS_TTL:
        return {k: v for k, v in cached.items() if k != "_ts"}
    result = _compute_technical_signals(db)
    _signals_cache["v"] = {**result, "_ts": time.time()}
    return result


def _compute_technical_signals(db: Session, target_date: date | None = None) -> dict:
    """
    Compute composite scores as they would have been on `target_date` (default today).

    Time-awareness is essential for the snapshot backfill path: only trades, whale
    filings, and price bars dated on-or-before `target_date` count. Callers flag
    reconstructed rows via `is_backfilled` so the win-rate stats stay honest.
    """
    target_date = target_date or date.today()
    is_historical = target_date < date.today()
    cutoff = target_date - timedelta(days=45)

    rows = (
        db.query(Trade.ticker, Trade.direction, Trade.trade_date, Trade.amount_low, Trade.amount_high)
        .join(Politician)
        .filter(
            Politician.is_tracked == True,  # noqa: E712
            Trade.trade_date >= cutoff,
            Trade.trade_date <= target_date,
        )
        .all()
    )

    ticker_activity: dict[str, dict] = {}
    for ticker, direction, td, lo, hi in rows:
        if not ticker:
            continue
        if ticker not in ticker_activity:
            ticker_activity[ticker] = {"buys": 0, "sells": 0, "buy_dollars": 0, "sell_dollars": 0, "last_trade_date": None}
        dollars = sem.amount_midpoint(lo, hi) or _DEFAULT_TRADE_DOLLARS
        # direction is NULL for exchanges, bonds and options with no call/put
        # in the filing — those still put the ticker in the universe (someone
        # in Congress touched it) but don't count as conviction either way.
        if direction == "buy":
            ticker_activity[ticker]["buys"] += 1
            ticker_activity[ticker]["buy_dollars"] += dollars
        elif direction == "sell":
            ticker_activity[ticker]["sells"] += 1
            ticker_activity[ticker]["sell_dollars"] += dollars
        if td and (ticker_activity[ticker]["last_trade_date"] is None or td > ticker_activity[ticker]["last_trade_date"]):
            ticker_activity[ticker]["last_trade_date"] = td

    tickers = list(ticker_activity.keys())
    if not tickers:
        return {"computed_at": datetime.now(timezone.utc).isoformat(), "signals": []}

    # ── Batch pre-fetch — 3 queries total instead of N×3 ─────────────────────

    # 1. All whale positions for active tickers (top 10 per ticker, desc by date).
    # Cap at target_date so backfill doesn't see filings that hadn't been
    # disclosed yet on the historical date being scored.
    all_positions = (
        db.query(WhalePosition)
        .join(WhaleHolder)
        .filter(
            WhaleHolder.is_tracked == True,  # noqa: E712
            WhalePosition.ticker.in_(tickers),
            WhalePosition.filing_date <= target_date,
        )
        .order_by(WhalePosition.filing_date.desc())
        .all()
    )
    positions_by_ticker: dict[str, list] = {t: [] for t in tickers}
    for p in all_positions:
        bucket = positions_by_ticker.get(p.ticker)
        if bucket is not None and len(bucket) < 10:
            bucket.append(p)

    # 2. Recent trades for risk penalty (bounded to target_date for backfill)
    all_risk_trades = (
        db.query(Trade)
        .join(Politician)
        .filter(
            Politician.is_tracked == True,  # noqa: E712
            Trade.ticker.in_(tickers),
            Trade.trade_date >= cutoff,
            Trade.trade_date <= target_date,
        )
        .all()
    )
    risk_trades_by_ticker: dict[str, list] = {t: [] for t in tickers}
    for t in all_risk_trades:
        bucket = risk_trades_by_ticker.get(t.ticker)
        if bucket is not None:
            bucket.append(t)

    # 3. Form 4 open-market trades in the last 90 days (bounded to target_date
    #    by filing date — that's when the market could have known).
    f4_cutoff = target_date - timedelta(days=90)
    all_f4 = (
        db.query(Form4Transaction)
        .filter(
            Form4Transaction.ticker.in_(tickers),
            Form4Transaction.transaction_type.in_(["buy", "sell"]),
            Form4Transaction.filing_date <= target_date,
            Form4Transaction.transaction_date >= f4_cutoff,
        )
        .all()
    )
    f4_by_ticker: dict[str, list] = {t: [] for t in tickers}
    for t in all_f4:
        bucket = f4_by_ticker.get(t.ticker)
        if bucket is not None:
            bucket.append(t)

    # 4. Latest whale filing date per ticker (bounded to target_date)
    filing_rows = (
        db.query(WhalePosition.ticker, func.max(WhalePosition.filing_date).label("max_date"))
        .filter(
            WhalePosition.ticker.in_(tickers),
            WhalePosition.filing_date <= target_date,
        )
        .group_by(WhalePosition.ticker)
        .all()
    )
    latest_filing_by_ticker = {r.ticker: r.max_date for r in filing_rows}

    # ── Parallel price-history fetch ─────────────────────────────────────────
    # yfinance is blocking IO — threads parallelise well. Most calls hit the
    # 24h history cache and return instantly; only cold tickers actually fan
    # out. Cap concurrency to avoid hammering the upstream rate limits.
    # For historical target_dates we ask for a larger window (covers SMA50)
    # and slice client-side, so we keep reusing the existing 24h cache.
    fetch_days = 120 if is_historical else 60
    history_by_ticker: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(get_price_history, t, fetch_days): t for t in tickers}
        for fut in futures:
            t = futures[fut]
            try:
                history_by_ticker[t] = fut.result()
            except Exception:
                history_by_ticker[t] = []

    target_iso = target_date.isoformat()
    results = []
    for ticker, activity in sorted(ticker_activity.items()):
        full_history = history_by_ticker.get(ticker, [])
        # Drop bars dated after target_date — they didn't exist yet.
        history = [h for h in full_history if h.get("date", "") <= target_iso] if is_historical else full_history
        closes = [h["close"] for h in history]
        is_demo = bool(history and history[-1].get("_demo"))

        momentum_pts, momentum_reasons = _momentum_score(closes)
        insider_pts, insider_reasons = _insider_score(
            activity["buys"], activity["sells"], activity["buy_dollars"], activity["sell_dollars"])
        corporate_pts, corporate_reasons = _corporate_score(f4_by_ticker.get(ticker, []))
        smart_pts, smart_reasons = _smart_money_from_positions(positions_by_ticker.get(ticker, []))
        risk_penalty_pts, risk_reasons = _risk_penalty_from_trades(risk_trades_by_ticker.get(ticker, []))

        composite = max(0, min(100,
            smart_pts + insider_pts + corporate_pts + momentum_pts - risk_penalty_pts
        ))

        raw_score = 0
        sma20 = _sma(closes, 20)
        sma50 = _sma(closes, 50)
        rsi = _rsi(closes)
        current = closes[-1] if closes else None
        if sma20 and sma50:
            raw_score += 1 if sma20 > sma50 else -1
        if current and sma20:
            raw_score += 1 if current > sma20 else -1
        if rsi is not None:
            if rsi < 30:
                raw_score += 1
            elif rsi > 70:
                raw_score -= 1
        if activity["buy_dollars"] > activity["sell_dollars"]:
            raw_score += 1
        elif activity["sell_dollars"] > activity["buy_dollars"]:
            raw_score -= 1
        if corporate_pts >= 18:
            raw_score += 1
        elif corporate_pts <= 7:
            raw_score -= 1

        all_reasons = smart_reasons + insider_reasons + corporate_reasons + momentum_reasons + risk_reasons
        last_filing = latest_filing_by_ticker.get(ticker)
        last_trade_date = activity["last_trade_date"].isoformat() if activity.get("last_trade_date") else None

        results.append({
            "ticker": ticker,
            "signal": _bullish_label(raw_score),
            "score": raw_score,
            "composite_score": composite,
            "label": _composite_label(composite),
            "current_price": round(current, 2) if current else None,
            "is_demo": is_demo,
            "sma20": sma20,
            "sma50": sma50,
            "rsi": rsi,
            "reasons": all_reasons,
            "insider_buys": activity["buys"],
            "insider_sells": activity["sells"],
            "insider_buy_dollars": activity["buy_dollars"],
            "insider_sell_dollars": activity["sell_dollars"],
            "corporate_buys": sum(1 for t in f4_by_ticker.get(ticker, []) if t.transaction_type == "buy"),
            "corporate_sells": sum(1 for t in f4_by_ticker.get(ticker, []) if t.transaction_type == "sell"),
            "window_start": cutoff.isoformat(),
            "window_end": target_date.isoformat(),
            "last_trade_date": last_trade_date,
            "last_filing_date": last_filing.isoformat() if last_filing else None,
            "sub_scores": {
                "smart_money": smart_pts,
                "insider": insider_pts,
                "corporate": corporate_pts,
                "momentum": momentum_pts,
                "risk_penalty": risk_penalty_pts,
            },
        })

    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return {"computed_at": datetime.now(timezone.utc).isoformat(), "score_version": SCORE_VERSION, "signals": results}
