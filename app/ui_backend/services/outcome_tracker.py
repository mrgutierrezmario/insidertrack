"""
Outcome tracker — two jobs:

  snapshot_signals(db)
    Called once daily. Reads current signal scores + prices and inserts one
    SignalOutcome row per ticker (skips if today's row already exists).

  fill_outcomes(db)
    Called once daily. Finds rows old enough for 30/60/90-day lookbacks,
    fetches the price on that future date from price history, and writes
    return % + UP/DOWN/FLAT outcome.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from models.signal_outcome import SignalOutcome
from services.market_data import get_price_history

logger = logging.getLogger(__name__)

FLAT_THRESHOLD = 2.0   # ±2% counts as FLAT


def _add_trading_days(start: date, n: int) -> date:
    """Advance `n` trading days from `start` (skipping weekends).

    Does not account for US market holidays — close enough for a coarse
    30/60/90-day lookback comparison, and removes the calendar-day drift that
    used to push the comparison off by a weekend.
    """
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 0-4 = Mon-Fri
            added += 1
    return d


def _outcome_label(pct: float) -> str:
    if pct >= FLAT_THRESHOLD:
        return "UP"
    if pct <= -FLAT_THRESHOLD:
        return "DOWN"
    return "FLAT"


def _price_on_date(history: list[dict], target: date) -> float | None:
    """Return the close price on or nearest-before target date."""
    best = None
    best_date = None
    for row in history:
        try:
            d = date.fromisoformat(row["date"])
        except Exception:
            continue
        if d <= target:
            if best_date is None or d > best_date:
                best_date = d
                best = row["close"]
    return best


def _politician_by_ticker(db: Session, tickers: list[str]) -> dict[str, dict]:
    """
    Return a dict mapping ticker → {id, name} for the most recent tracked-politician
    trade per ticker. Uses max(trade_date) to break ties deterministically.
    """
    if not tickers:
        return {}
    from models.politician import Politician
    from models.trade import Trade

    subq = (
        db.query(Trade.ticker, func.max(Trade.trade_date).label("max_date"))
        .join(Politician)
        .filter(Politician.is_tracked == True, Trade.ticker.in_(tickers))  # noqa: E712
        .group_by(Trade.ticker)
        .subquery()
    )
    rows = (
        db.query(Trade.ticker, Politician.id, Politician.name)
        .join(Politician)
        .join(subq, (Trade.ticker == subq.c.ticker) & (Trade.trade_date == subq.c.max_date))
        .filter(Politician.is_tracked == True)  # noqa: E712
        .all()
    )
    return {t: {"id": pid, "name": pname} for t, pid, pname in rows}


def snapshot_signals(db: Session, target_date: date | None = None) -> int:
    """
    Snapshot signal scores into signal_outcomes for `target_date` (default today).

    Returns number of new rows inserted. Demo-price rows are skipped so synthetic
    prices never enter the win-rate computation. The (ticker, signal_date) unique
    index + ON CONFLICT DO NOTHING makes this idempotent — re-running on the same
    day is a no-op.

    When `target_date` is in the past, rows are flagged `is_backfilled=True` and
    sentiment is reconstructed as neutral (50) — see `_compute_technical_signals`.
    """
    from routers.signals import technical_signals, _compute_technical_signals

    today = date.today()
    target_date = target_date or today
    is_backfilled = target_date < today

    try:
        # Live path uses the cached `technical_signals`; backfill goes straight
        # to the time-aware computation so it can pass a date.
        if is_backfilled:
            signals = _compute_technical_signals(db, target_date=target_date).get("signals", [])
        else:
            signals = technical_signals(db).get("signals", [])
    except Exception as e:
        logger.error(f"Could not compute signals for snapshot ({target_date}): {e}")
        return 0

    tickers = [s.get("ticker") for s in signals if s.get("ticker")]
    pol_map = _politician_by_ticker(db, tickers)

    rows = []
    skipped_demo = 0
    for s in signals:
        ticker = s.get("ticker")
        price  = s.get("current_price")
        if not ticker or not price:
            continue
        if s.get("is_demo"):
            skipped_demo += 1
            continue
        sub = s.get("sub_scores", {})
        pol = pol_map.get(ticker, {})
        rows.append({
            "ticker":            ticker,
            "signal_date":       target_date,
            "composite_score":   s.get("composite_score"),
            "label":             s.get("label"),
            "signal":            s.get("signal"),
            "price_at_signal":   price,
            "politician_id":     pol.get("id"),
            "politician_name":   pol.get("name"),
            "smart_money_score": sub.get("smart_money"),
            "insider_score":     sub.get("insider"),
            "momentum_score":    sub.get("momentum"),
            "sentiment_score":   sub.get("sentiment"),
            "risk_penalty":      sub.get("risk_penalty"),
            "is_backfilled":     is_backfilled,
        })

    if not rows:
        if skipped_demo:
            logger.warning(f"All {skipped_demo} signals had demo prices — nothing snapshotted for {target_date}")
        return 0

    stmt = (
        pg_insert(SignalOutcome.__table__)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["ticker", "signal_date"])
    )
    result = db.execute(stmt)
    db.commit()
    inserted = result.rowcount or 0
    tag = " [backfill]" if is_backfilled else ""
    logger.info(
        f"Snapshotted {inserted} signal outcomes for {target_date}{tag}"
        + (f" (skipped {skipped_demo} demo-price tickers)" if skipped_demo else "")
    )
    return inserted


def backfill_snapshot_gaps(db: Session, window_days: int = 14) -> dict:
    """
    For every weekday in the last `window_days` with no signal_outcomes row,
    reconstruct the score retrospectively and insert it (flagged is_backfilled).

    Limitations baked into the reconstruction:
      • News sentiment can't be backfilled — treated as neutral 50.
      • Whale 13F filings are quarterly; the snapshot uses whatever filings
        were dated on-or-before the target date.
      • Daily price bars must exist in the yfinance cache window (we widen to
        120 days for backfill — see `_compute_technical_signals`).

    Returns a small summary dict: {"days_filled": int, "rows_inserted": int,
    "days_skipped": int}. Idempotent — re-running is a no-op thanks to the
    `(ticker, signal_date)` unique index.
    """
    gaps = detect_snapshot_gaps(db, window_days=window_days)
    if not gaps:
        return {"days_filled": 0, "rows_inserted": 0, "days_skipped": 0}

    rows_inserted = 0
    days_filled = 0
    days_skipped = 0
    for day in gaps:
        inserted = snapshot_signals(db, target_date=day)
        if inserted > 0:
            days_filled += 1
            rows_inserted += inserted
        else:
            days_skipped += 1
    logger.info(
        f"Backfill complete: {days_filled} day(s) filled with {rows_inserted} row(s), "
        f"{days_skipped} day(s) had no scorable tickers"
    )
    return {"days_filled": days_filled, "rows_inserted": rows_inserted, "days_skipped": days_skipped}


def detect_snapshot_gaps(db: Session, window_days: int = 14) -> list[date]:
    """
    Return weekdays in the past `window_days` that have no `signal_outcomes`
    row. Used as a coarse "did the snapshot job run?" check at startup and
    surfaced on /health so operators notice when the server was down at
    07:00 ET. Weekends are skipped — market is closed.
    """
    today = date.today()
    start = today - timedelta(days=window_days)
    existing = {
        d for (d,) in db.query(SignalOutcome.signal_date)
        .filter(SignalOutcome.signal_date >= start, SignalOutcome.signal_date <= today)
        .distinct()
        .all()
    }
    expected = []
    d = start
    while d <= today:
        if d.weekday() < 5:  # weekday only
            expected.append(d)
        d += timedelta(days=1)
    return [d for d in expected if d not in existing]


def fill_outcomes(db: Session) -> int:
    """
    Fill in 30/60/90-day price outcomes for rows old enough.
    Returns number of rows updated.

    Fetches one ~100-day price history per ticker and slices all three windows
    from it, instead of refetching per window (3× the external calls).
    """
    today = date.today()
    updated = 0

    windows = [
        (30, "price_30d", "return_30d", "outcome_30d"),
        (60, "price_60d", "return_60d", "outcome_60d"),
        (90, "price_90d", "return_90d", "outcome_90d"),
    ]

    # ── Pull every pending row across all windows in one query ──────────────
    # Use a calendar-day cutoff as a conservative pre-filter; the per-row
    # eligibility check below uses trading days for the actual target date.
    fill_cutoff = today - timedelta(days=windows[0][0])
    pending_rows = (
        db.query(SignalOutcome)
        .filter(
            SignalOutcome.signal_date <= fill_cutoff,
            SignalOutcome.price_at_signal != None,  # noqa: E711
            (
                (SignalOutcome.outcome_30d == None)  # noqa: E711
                | (SignalOutcome.outcome_60d == None)
                | (SignalOutcome.outcome_90d == None)
            ),
        )
        .all()
    )

    by_ticker: dict[str, list[SignalOutcome]] = {}
    for row in pending_rows:
        by_ticker.setdefault(row.ticker, []).append(row)

    # ── One history fetch per ticker, slice all three windows from it ───────
    for ticker, ticker_rows in by_ticker.items():
        try:
            history = get_price_history(ticker, days=windows[-1][0] + 10)  # 100 days
        except Exception:
            continue

        for row in ticker_rows:
            for days, price_col, return_col, outcome_col in windows:
                if getattr(row, outcome_col) is not None:
                    continue
                target_date = _add_trading_days(row.signal_date, days)
                if target_date > today:
                    continue  # not yet eligible for this window

                future_price = _price_on_date(history, target_date)
                if future_price is None:
                    continue

                pct = round((future_price - row.price_at_signal) / row.price_at_signal * 100, 2)
                setattr(row, price_col,   round(future_price, 2))
                setattr(row, return_col,  pct)
                setattr(row, outcome_col, _outcome_label(pct))
                updated += 1

    db.commit()
    logger.info(f"Filled outcomes for {updated} rows")
    return updated
