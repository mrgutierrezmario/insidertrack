"""
Projects profit/loss if user invests $X into a ticker today,
assuming they entered when the tracked politician's trade was disclosed.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.politician import Politician
from models.trade import Trade
from services.market_data import get_current_price, get_price_history

router = APIRouter(prefix="/simulator", tags=["simulator"])


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

    history = get_price_history(ticker, days=365)
    if not history:
        raise HTTPException(status_code=502, detail=f"Could not fetch price history for {ticker}")

    # Find price on or after disclosure date
    entry_price = None
    entry_date_str = str(entry_trade.disclosure_date)
    for bar in history:
        if bar["date"] >= entry_date_str:
            entry_price = bar["close"]
            entry_date_used = bar["date"]
            break

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
        "entry_date": entry_date_used,
        "entry_price": round(entry_price, 2),
        "current_price": round(current_price, 2),
        "is_demo": is_demo,
        "shares": round(shares, 4),
        "current_value": round(current_value, 2),
        "profit": round(profit, 2),
        "pct_return": round(pct_return, 2),
        "triggered_by": entry_trade.politician.name if entry_trade.politician else "unknown",
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

    history = get_price_history(ticker, days=365)
    if not history:
        raise HTTPException(status_code=502, detail=f"Could not fetch price history for {ticker}")

    entry_date_str = str(entry_trade.disclosure_date)
    entry_price = None
    points = []

    for bar in history:
        if bar["date"] >= entry_date_str:
            if entry_price is None:
                entry_price = bar["close"]
            points.append({"date": bar["date"], "value": round((bar["close"] / entry_price) * amount, 2)})

    if not points:
        raise HTTPException(status_code=404, detail="No price history after entry date")

    # SPY comparison — same dollar amount invested on same entry date
    spy_history = get_price_history("SPY", days=365)
    spy_points = []
    spy_entry_price = None
    for bar in spy_history or []:
        if bar["date"] >= entry_date_str:
            if spy_entry_price is None:
                spy_entry_price = bar["close"]
            spy_points.append({"date": bar["date"], "value": round((bar["close"] / spy_entry_price) * amount, 2)})

    return {
        "ticker": ticker,
        "investment": amount,
        "entry_date": entry_date_str,
        "entry_price": round(entry_price, 2) if entry_price else None,
        "triggered_by": entry_trade.politician.name if entry_trade.politician else "unknown",
        "points": points,
        "spy_points": spy_points,
    }
