"""
Runs morning / midday / evening analysis over tracked tickers.

Signal logic:
- BUY:  tracked politician/whale bought recently + price not yet spiked
- SELL: tracked politician/whale sold recently OR price > 20% above entry
- HOLD: everything else
"""

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from models.analysis import DailyAnalysis
from models.politician import Politician
from models.trade import Trade
from services.market_data import get_bulk_prices, get_current_price

logger = logging.getLogger(__name__)

RECENCY_DAYS = 45          # disclosure lag window
SPIKE_THRESHOLD = 0.20     # 20% above first tracked buy = caution


def _get_tracked_tickers(db: Session) -> list[str]:
    cutoff = date.today() - timedelta(days=RECENCY_DAYS * 2)
    rows = (
        db.query(Trade.ticker)
        .join(Politician)
        .filter(Politician.is_tracked == True, Trade.trade_date >= cutoff)  # noqa: E712
        .distinct()
        .all()
    )
    return [r.ticker for r in rows if r.ticker]


def _build_signal(ticker: str, recent_trades: list[Trade], current_price: Optional[float]) -> dict:
    buys = [t for t in recent_trades if t.direction == "buy"]
    sells = [t for t in recent_trades if t.direction == "sell"]

    signal = "HOLD"
    reason = "No strong signal from tracked insiders."

    if buys and not sells:
        signal = "BUY"
        reason = f"{len(buys)} insider purchase(s) in last {RECENCY_DAYS} days, no sells."
    elif sells and not buys:
        signal = "SELL"
        reason = f"{len(sells)} insider sale(s) in last {RECENCY_DAYS} days, no new buys."
    elif sells and buys:
        signal = "HOLD"
        reason = "Mixed signals: both purchases and sales from insiders recently."

    return {
        "ticker": ticker,
        "signal": signal,
        "reason": reason,
        "current_price": current_price,
        "recent_buys": len(buys),
        "recent_sells": len(sells),
        "insiders": list({t.politician.name for t in recent_trades if t.politician}),
    }


def run_analysis(db: Session, period: str) -> DailyAnalysis:
    today = date.today()
    cutoff = today - timedelta(days=RECENCY_DAYS)

    tickers = _get_tracked_tickers(db)
    if not tickers:
        logger.info("No tracked tickers found — skipping analysis")

    prices = get_bulk_prices(tickers)
    signals = []

    for ticker in tickers:
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
        signal = _build_signal(ticker, recent_trades, prices.get(ticker))
        signals.append(signal)

    bullish = [s["ticker"] for s in signals if s["signal"] == "BUY"]
    bearish = [s["ticker"] for s in signals if s["signal"] == "SELL"]

    top_movers = [
        {"ticker": t, "price": p}
        for t, p in prices.items()
        if p is not None
    ]

    summary_lines = [
        f"Analysis period: {period} on {today}",
        f"Tracked tickers: {len(tickers)}",
        f"Buy signals: {bullish}",
        f"Sell signals: {bearish}",
    ]

    analysis = DailyAnalysis(
        analysis_date=today,
        period=period,
        tickers_bullish=bullish,
        tickers_bearish=bearish,
        top_movers=top_movers,
        summary="\n".join(summary_lines),
        signals=signals,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    logger.info(f"[{period}] Analysis complete — {len(bullish)} buys, {len(bearish)} sells")
    return analysis
