"""
Late filers — who discloses their trades after the STOCK Act's deadline.

A periodic transaction report is due 30 days after the member is notified of
a trade and never later than 45 days after the trade itself. Filings don't
always carry the notification date (Senate PTRs never do), so the measurable
rule is the outer one: a row is late when it was disclosed more than 45 days
after the transaction. Amended rows keep the original report's disclosure
date (see congress_fetcher), so an amendment doesn't make a trade look late.

Computed in Python over plain columns so it behaves the same on PostgreSQL
and the SQLite test database (date subtraction differs between them).
"""

from datetime import date, timedelta
from statistics import median

from sqlalchemy.orm import Session

from models.politician import Politician
from models.trade import Trade

LATE_AFTER_DAYS = 45


def lag_days(trade_date: date | None, disclosure_date: date | None) -> int | None:
    if not trade_date or not disclosure_date:
        return None
    return (disclosure_date - trade_date).days


def is_late(trade_date: date | None, disclosure_date: date | None) -> bool:
    lag = lag_days(trade_date, disclosure_date)
    return lag is not None and lag > LATE_AFTER_DAYS


def late_filers(db: Session, days: int | None = None, today: date | None = None) -> dict:
    """Members ranked by how many of their trades were disclosed late.

    `days` limits to trades disclosed in the last N days (None = all
    history). Members with no late trade in the window are left out; their
    trades still count toward the window's totals.
    """
    from routers.trades import _filing_url

    q = (
        db.query(Trade.politician_id, Trade.trade_date, Trade.disclosure_date,
                 Trade.filing_id, Trade.source)
        .filter(Trade.trade_date.isnot(None), Trade.disclosure_date.isnot(None))
    )
    if days:
        q = q.filter(Trade.disclosure_date >= (today or date.today()) - timedelta(days=days))

    per: dict[int, dict] = {}
    total = late_total = 0
    for row in q.all():
        total += 1
        m = per.setdefault(row.politician_id, {"total": 0, "lags": [], "filings": set(), "worst": None, "latest": None})
        m["total"] += 1
        lag = lag_days(row.trade_date, row.disclosure_date)
        if lag is None or lag <= LATE_AFTER_DAYS:
            continue
        late_total += 1
        m["lags"].append(lag)
        if row.filing_id:
            m["filings"].add(row.filing_id)
        if m["worst"] is None or lag > m["worst"][0]:
            m["worst"] = (lag, row)
        if m["latest"] is None or row.disclosure_date > m["latest"]:
            m["latest"] = row.disclosure_date

    late_ids = [pid for pid, m in per.items() if m["lags"]]
    people = {p.id: p for p in db.query(Politician).filter(Politician.id.in_(late_ids)).all()} if late_ids else {}

    items = []
    for pid in late_ids:
        m, p = per[pid], people.get(pid)
        if p is None:
            continue
        worst_lag, worst = m["worst"]
        items.append({
            "id": p.id,
            "name": p.name,
            "party": p.party,
            "chamber": p.chamber,
            "state": p.state,
            "trades": m["total"],
            "late_trades": len(m["lags"]),
            "late_pct": round(len(m["lags"]) / m["total"] * 100, 1),
            "late_filings": len(m["filings"]),
            "median_lag_days": int(median(m["lags"])),
            "worst": {
                "lag_days": worst_lag,
                "trade_date": worst.trade_date.isoformat(),
                "disclosure_date": worst.disclosure_date.isoformat(),
                "filing_url": _filing_url(worst),
            },
            "latest_late_disclosure": m["latest"].isoformat(),
        })
    items.sort(key=lambda r: (r["late_trades"], r["late_pct"]), reverse=True)

    return {
        "late_after_days": LATE_AFTER_DAYS,
        "window_days": days,
        "trades": total,
        "late_trades": late_total,
        "late_pct": round(late_total / total * 100, 1) if total else None,
        "members_with_trades": len(per),
        "members_late": len(items),
        "items": items,
    }
