"""services.alert_engine — rule evaluation end-to-end on SQLite, external feeds stubbed."""

from datetime import date, timedelta

import pytest

from services import alert_engine as ae


@pytest.fixture(autouse=True)
def _quiet_feeds(monkeypatch):
    """Signals/earnings come from routers that hit the network; stub them."""
    import routers.signals as rs
    import services.earnings_fetcher as ef
    monkeypatch.setattr(rs, "technical_signals", lambda db: {"signals": [
        {"ticker": "AAPL", "composite_score": 80, "label": "Strong Watch", "signal": "BULLISH", "rsi": 55},
        {"ticker": "XOM", "composite_score": 40, "label": "Neutral", "signal": "BEARISH", "rsi": 60},
    ]})
    monkeypatch.setattr(ef, "get_earnings_calendar", lambda tickers: [
        {"ticker": "AAPL", "is_upcoming": True, "days_until": 3, "report_date": "2026-09-22"},
        {"ticker": "XOM", "is_upcoming": True, "days_until": 20, "report_date": "2026-10-09"},
    ])
    sent = []
    monkeypatch.setattr(ae, "_send_notifications", lambda db, rules, events: sent.append(events))
    yield sent


@pytest.fixture()
def clean(db):
    from models.alert import AlertEvent, AlertRule
    db.query(AlertEvent).delete(); db.query(AlertRule).delete(); db.commit()
    yield db


def _rule(db, alert_type, ticker=None, threshold=None, name=None):
    from models.alert import AlertRule
    r = AlertRule(name=name or alert_type, alert_type=alert_type, ticker=ticker, threshold=threshold, is_active=True)
    db.add(r); db.flush()
    return r


class TestEvaluate:
    def test_no_rules(self, clean):
        assert ae.evaluate_alerts(clean) == {"rules": 0, "new_events": 0, "events": []}

    def test_high_signal_threshold_and_ticker_filter(self, clean):
        _rule(clean, "high_signal", threshold=70)                 # any ticker
        _rule(clean, "high_signal", ticker="xom", threshold=30)   # ticker match is case-insensitive
        out = ae.evaluate_alerts(clean)
        assert out["new_events"] == 2
        assert sorted(e["ticker"] for e in out["events"]) == ["AAPL", "XOM"]

    def test_momentum_only_bullish(self, clean):
        _rule(clean, "momentum")
        out = ae.evaluate_alerts(clean)
        assert [e["ticker"] for e in out["events"]] == ["AAPL"]

    def test_events_are_deduplicated_across_runs(self, clean):
        _rule(clean, "high_signal", threshold=70)
        assert ae.evaluate_alerts(clean)["new_events"] == 1
        assert ae.evaluate_alerts(clean)["new_events"] == 0   # same day, same ticker → no second event

    def test_earnings_window(self, clean):
        _rule(clean, "earnings_soon", threshold=7)
        out = ae.evaluate_alerts(clean)
        assert [e["ticker"] for e in out["events"]] == ["AAPL"]   # XOM is 20 days out

    def test_insider_buy_uses_direction_not_verb(self, clean):
        from models.politician import Politician
        from models.trade import Trade
        p = Politician(name="Rep Alerts", chamber="house", is_tracked=True)
        clean.add(p); clean.flush()
        recent = date.today() - timedelta(days=2)
        clean.add_all([
            # a stock purchase → fires
            Trade(politician_id=p.id, ticker="NVDA", transaction_type="purchase", direction="buy",
                  amount_range="$1,001 - $15,000", trade_date=recent, source="house", raw_data="{}"),
            # a put purchase: verb says "purchase", direction says sell → must NOT fire
            Trade(politician_id=p.id, ticker="MSFT", transaction_type="purchase", direction="sell",
                  asset_type="option", amount_range="$1,001 - $15,000", trade_date=recent, source="house", raw_data="{}"),
            # too old
            Trade(politician_id=p.id, ticker="AAPL", transaction_type="purchase", direction="buy",
                  amount_range="$1,001 - $15,000", trade_date=date.today() - timedelta(days=30), source="house", raw_data="{}"),
        ])
        clean.flush()
        _rule(clean, "insider_buy", threshold=7)
        out = ae.evaluate_alerts(clean)
        assert [e["ticker"] for e in out["events"]] == ["NVDA"]
        assert "Rep Alerts disclosed a purchase of NVDA" in out["events"][0]["message"]

    def test_inactive_rules_are_ignored(self, clean):
        r = _rule(clean, "high_signal", threshold=0)
        r.is_active = False; clean.flush()
        assert ae.evaluate_alerts(clean)["rules"] == 0

    def test_notifications_get_the_new_events(self, clean, _quiet_feeds):
        _rule(clean, "momentum")
        ae.evaluate_alerts(clean)
        assert _quiet_feeds and _quiet_feeds[-1][0]["ticker"] == "AAPL"
