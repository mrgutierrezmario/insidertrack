"""
Projects profit/loss if user invests $X into a ticker today,
assuming they entered when the tracked politician's trade was disclosed.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.politician import Politician
from models.trade import Trade
from services.market_data import get_current_price, get_price_history

router = APIRouter(prefix="/simulator", tags=["simulator"])


def _history_since(ticker: str, since: str) -> list[dict]:
    """Daily history reaching back to ``since`` (at least a year)."""
    days = max(365, (date.today() - date.fromisoformat(since)).days + 10)
    return get_price_history(ticker, days=days)


def _entry_bar(history: list[dict], since: str) -> Optional[dict]:
    """The first trading day on or after ``since``: the day you could have bought."""
    return next((bar for bar in history if bar["date"] >= since), None)


@router.get("/project")
def project_investment(
    ticker: str,
    amount: float = 100.0,
    db: Session = Depends(get_db),
):
    ticker = ticker.upper()

    # Find the earliest tracked-politician buy for this ticker
    entry_trade = (
        db.query(Trade)
        .join(Politician)
        .filter(
            Politician.is_tracked == True,  # noqa: E712
            Trade.ticker == ticker,
            Trade.direction == "buy",
        )
        .order_by(Trade.disclosure_date.asc())
        .first()
    )

    if not entry_trade:
        raise HTTPException(
            status_code=404,
            detail=f"No tracked buy for {ticker}. Try syncing trades first.",
        )

    entry_date_str = str(entry_trade.disclosure_date)
    triggered_by = entry_trade.politician.name if entry_trade.politician else "unknown"
    # Done with the database: close the session before the network fetches
    # below, so a slow or hung fetch can't hold a transaction (and its locks)
    # open. Columns already loaded stay readable.
    db.close()

    history = _history_since(ticker, entry_date_str)
    if not history:
        raise HTTPException(status_code=502, detail=f"Could not fetch price history for {ticker}")

    entry_bar = _entry_bar(history, entry_date_str)
    entry_price = entry_bar["close"] if entry_bar else None

    price_meta = get_current_price(ticker, with_meta=True)
    current_price = price_meta["price"]
    is_demo = price_meta["is_demo"]

    if not entry_price or not current_price:
        raise HTTPException(status_code=502, detail="Could not compute entry/current price")

    shares = amount / entry_price
    current_value = shares * current_price
    profit = current_value - amount
    pct_return = (profit / amount) * 100

    return {
        "ticker": ticker,
        "investment": amount,
        "entry_date": entry_bar["date"],
        "disclosure_date": entry_date_str,
        "entry_price": round(entry_price, 2),
        "current_price": round(current_price, 2),
        "is_demo": is_demo,
        "shares": round(shares, 4),
        "current_value": round(current_value, 2),
        "profit": round(profit, 2),
        "pct_return": round(pct_return, 2),
        "triggered_by": triggered_by,
    }


@router.get("/growth")
def growth_simulation(
    ticker: str,
    amount: float = 100.0,
    db: Session = Depends(get_db),
):
    """Day-by-day portfolio value from politician's entry date to today."""
    ticker = ticker.upper()

    entry_trade = (
        db.query(Trade)
        .join(Politician)
        .filter(
            Politician.is_tracked == True,  # noqa: E712
            Trade.ticker == ticker,
            Trade.direction == "buy",
        )
        .order_by(Trade.disclosure_date.asc())
        .first()
    )

    if not entry_trade:
        raise HTTPException(
            status_code=404,
            detail=f"No tracked buy for {ticker}.",
        )

    entry_date_str = str(entry_trade.disclosure_date)
    triggered_by = entry_trade.politician.name if entry_trade.politician else "unknown"
    # Done with the database: close the session before the network fetches
    # below, so a slow or hung fetch can't hold a transaction (and its locks)
    # open. Columns already loaded stay readable.
    db.close()

    history = _history_since(ticker, entry_date_str)
    if not history:
        raise HTTPException(status_code=502, detail=f"Could not fetch price history for {ticker}")

    entry_bar = _entry_bar(history, entry_date_str)
    if not entry_bar:
        raise HTTPException(status_code=404, detail="No price history after entry date")
    entry_price = entry_bar["close"]
    points = [
        {"date": bar["date"], "value": round((bar["close"] / entry_price) * amount, 2)}
        for bar in history
        if bar["date"] >= entry_bar["date"]
    ]

    # SPY comparison: the same dollars invested on the same day.
    spy_history = _history_since("SPY", entry_bar["date"]) or []
    spy_entry = _entry_bar(spy_history, entry_bar["date"])
    spy_points = (
        [
            {"date": bar["date"], "value": round((bar["close"] / spy_entry["close"]) * amount, 2)}
            for bar in spy_history
            if bar["date"] >= spy_entry["date"]
        ]
        if spy_entry
        else []
    )

    return {
        "ticker": ticker,
        "investment": amount,
        "entry_date": entry_bar["date"],
        "disclosure_date": entry_date_str,
        "entry_price": round(entry_price, 2),
        "triggered_by": triggered_by,
        "points": points,
        "spy_points": spy_points,
    }
