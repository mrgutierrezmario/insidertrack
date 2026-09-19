"""
Alert engine — evaluates user-defined AlertRules and records AlertEvents.

Supported alert_type values:
  high_signal    — composite signal score >= threshold
  momentum       — ticker shows a BULLISH technical signal
  insider_buy    — a tracked politician disclosed a purchase in the last `threshold` days
  whale_new      — an institution opened a NEW 13F position
  earnings_soon  — a tracked ticker has earnings within `threshold` days

Events are de-duplicated via a per-rule dedup_key so the same condition
does not fire repeatedly day after day.
"""

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from models.alert import AlertEvent, AlertRule
from models.politician import Politician
from models.trade import Trade
from models.whale import WhaleHolder, WhalePosition

logger = logging.getLogger(__name__)


def _emit(db: Session, rule: AlertRule, ticker: str, message: str, dedup_key: str) -> bool:
    """Create an AlertEvent if one with this dedup_key does not already exist."""
    exists = db.query(AlertEvent).filter(AlertEvent.dedup_key == dedup_key).first()
    if exists:
        return False
    db.add(AlertEvent(rule_id=rule.id, ticker=ticker, message=message, dedup_key=dedup_key))
    return True


def _matches_ticker(rule: AlertRule, ticker: str) -> bool:
    return not rule.ticker or rule.ticker.upper() == (ticker or "").upper()


def evaluate_alerts(db: Session) -> dict:
    """Run every active rule. Returns counts and the list of new events."""
    rules = db.query(AlertRule).filter(AlertRule.is_active == True).all()  # noqa: E712
    if not rules:
        return {"rules": 0, "new_events": 0, "events": []}

    today = date.today()
    new_events: list[dict] = []

    # Compute signals once and reuse across rules.
    signals = []
    try:
        from routers.signals import technical_signals
        signals = technical_signals(db).get("signals", [])
    except Exception as e:
        logger.warning(f"Alert engine could not load signals: {e}")

    # Earnings (best-effort — depends on AV key).
    earnings = []
    try:
        from routers.earnings import _tracked_tickers
        from services.earnings_fetcher import get_earnings_calendar
        earnings = get_earnings_calendar(_tracked_tickers(db))
    except Exception as e:
        logger.warning(f"Alert engine could not load earnings: {e}")

    for rule in rules:
        t = rule.alert_type
        thr = rule.threshold or 0

        if t == "high_signal":
            for s in signals:
                if not _matches_ticker(rule, s["ticker"]):
                    continue
                if (s.get("composite_score") or 0) >= thr:
                    key = f"{rule.id}:high_signal:{s['ticker']}:{today}"
                    msg = f"{s['ticker']} composite score {s['composite_score']} ({s['label']}) — at or above your {int(thr)} threshold."
                    if _emit(db, rule, s["ticker"], msg, key):
                        new_events.append({"ticker": s["ticker"], "message": msg, "rule": rule.name})

        elif t == "momentum":
            for s in signals:
                if not _matches_ticker(rule, s["ticker"]):
                    continue
                if s.get("signal") == "BULLISH":
                    key = f"{rule.id}:momentum:{s['ticker']}:{today}"
                    msg = f"{s['ticker']} is showing a BULLISH technical signal (RSI {s.get('rsi')}, SMA crossover)."
                    if _emit(db, rule, s["ticker"], msg, key):
                        new_events.append({"ticker": s["ticker"], "message": msg, "rule": rule.name})

        elif t == "insider_buy":
            window = int(thr) if thr else 7
            cutoff = today - timedelta(days=window)
            q = (
                db.query(Trade)
                .join(Politician)
                .filter(Politician.is_tracked == True, Trade.trade_date >= cutoff,  # noqa: E712
                        Trade.direction == "buy")
            )
            if rule.ticker:
                q = q.filter(Trade.ticker == rule.ticker.upper())
            for tr in q.all():
                key = f"{rule.id}:insider_buy:{tr.id}"
                who = tr.politician.name if tr.politician else "A tracked politician"
                msg = f"{who} disclosed a purchase of {tr.ticker} ({tr.amount_range or 'amount n/a'}) on {tr.trade_date}."
                if _emit(db, rule, tr.ticker, msg, key):
                    new_events.append({"ticker": tr.ticker, "message": msg, "rule": rule.name})

        elif t == "whale_new":
            cutoff = today - timedelta(days=120)
            q = (
                db.query(WhalePosition)
                .join(WhaleHolder)
                .filter(
                    WhaleHolder.is_tracked == True,  # noqa: E712
                    WhalePosition.change_type == "new",
                    WhalePosition.filing_date >= cutoff,
                )
            )
            if rule.ticker:
                q = q.filter(WhalePosition.ticker == rule.ticker.upper())
            for p in q.all():
                key = f"{rule.id}:whale_new:{p.id}"
                holder = p.holder.name if p.holder else "An institution"
                msg = f"{holder} opened a NEW position in {p.ticker} ({p.quarter})."
                if _emit(db, rule, p.ticker, msg, key):
                    new_events.append({"ticker": p.ticker, "message": msg, "rule": rule.name})

        elif t == "earnings_soon":
            window = int(thr) if thr else 7
            for e in earnings:
                if not e.get("is_upcoming"):
                    continue
                if not _matches_ticker(rule, e.get("ticker", "")):
                    continue
                days = e.get("days_until")
                if days is not None and days <= window:
                    key = f"{rule.id}:earnings:{e['ticker']}:{e.get('report_date')}"
                    msg = f"{e['ticker']} reports earnings on {e.get('report_date')} ({days} day(s) away)."
                    if _emit(db, rule, e["ticker"], msg, key):
                        new_events.append({"ticker": e["ticker"], "message": msg, "rule": rule.name})

    db.commit()

    # Email any rules that asked for notification.
    _send_notifications(db, rules, new_events)

    logger.info(f"Alert engine: {len(rules)} rules, {len(new_events)} new events")
    return {"rules": len(rules), "new_events": len(new_events), "events": new_events}


def _send_notifications(db: Session, rules: list[AlertRule], new_events: list[dict]) -> None:
    if not new_events:
        return
    by_rule_email: dict[str, list[dict]] = {}
    for rule in rules:
        if not rule.notify_email:
            continue
        matched = [e for e in new_events if e["rule"] == rule.name]
        if matched:
            by_rule_email.setdefault(rule.notify_email, []).extend(matched)

    if not by_rule_email:
        return
    try:
        from services.email_sender import send_simple_email
    except Exception:
        return

    import html as _html
    for email, events in by_rule_email.items():
        rows = "".join(
            f'<tr><td style="padding:8px 12px;color:#38bdf8;font-weight:700">{_html.escape(str(e.get("ticker", "")))}</td>'
            f'<td style="padding:8px 12px;color:#94a3b8;font-size:13px">{_html.escape(str(e.get("message", "")))}</td></tr>'
            for e in events
        )
        body = f"""<div style="background:#0f1117;padding:24px;font-family:-apple-system,sans-serif">
        <div style="max-width:600px;margin:0 auto">
        <h2 style="color:#38bdf8">InsiderTrack Alerts</h2>
        <p style="color:#64748b">{len(events)} alert(s) triggered.</p>
        <table style="width:100%;border-collapse:collapse;background:#161b27;border:1px solid #1e2533;border-radius:8px">
        {rows}</table>
        <p style="color:#4b5563;font-size:12px;margin-top:16px">Not financial advice. Based on delayed public disclosures.</p>
        </div></div>"""
        send_simple_email(f"InsiderTrack — {len(events)} new alert(s)", body, [email])
