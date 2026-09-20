"""services.model_desk — call validation, storage, resolution and stats (no provider calls)."""

from datetime import date, timedelta

from services import model_desk as md


def _series(start: date, n: int, step: float, base: float = 100.0):
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": round(base + i * step, 2)} for i in range(n)]


class _Gen:
    def __init__(self, text): self.text, self.provider = text, "test/model"


def test_generate_validates_and_stores(db, monkeypatch):
    from models.model_call import ModelBrief, ModelCall
    day = date(2026, 9, 20)
    monkeypatch.setattr(md, "build_context", lambda db_, d: {"date": d.isoformat(), "congress_recent": [{"ticker": "AAPL"}],
                        "insider_cluster_buys": [{"ticker": "GME"}], "top_scores": [{"ticker": "KMX"}], "bottom_scores": []})
    import services.providers as prov
    monkeypatch.setattr(prov, "active_provider", lambda: "test")
    monkeypatch.setattr(prov, "generate_text", lambda *a, **k: _Gen('''```json
{"summary": "Three things stand out.", "calls": [
  {"ticker": "aapl", "direction": "Bullish", "horizon_days": 30, "confidence": 0.7, "reasoning": "Members bought."},
  {"ticker": "GME", "direction": "bearish", "horizon_days": 60, "confidence": 0.4, "reasoning": "Insiders sold."},
  {"ticker": "MSFT", "direction": "bullish", "horizon_days": 30, "confidence": 0.9, "reasoning": "Not in data."},
  {"ticker": "KMX", "direction": "sideways", "horizon_days": 30, "confidence": 0.5, "reasoning": "Bad direction."},
  {"ticker": "AAPL", "direction": "bullish", "horizon_days": 90, "confidence": 0.5, "reasoning": "Duplicate."}
]}
```'''))
    monkeypatch.setattr(md, "get_price_history", lambda tk, days=30: [{"date": "2026-09-19", "close": 200.0}])
    out = md.generate_brief(db, day)
    assert out["status"] == "ok" and out["calls"] == 2
    assert set(out["rejected"]) == {"MSFT", "KMX", "AAPL"}          # unknown ticker, bad direction, duplicate
    calls = {c.ticker: c for c in db.query(ModelCall).filter(ModelCall.call_date == day)}
    assert calls["AAPL"].direction == "bullish" and calls["AAPL"].price_at_call == 200.0
    assert calls["GME"].horizon_days == 60
    assert db.query(ModelBrief).filter(ModelBrief.brief_date == day).one().summary.startswith("Three things")
    # idempotent
    assert md.generate_brief(db, day)["status"] == "exists"


def test_resolve_and_stats(db, monkeypatch):
    from models.model_call import ModelCall
    today = date(2026, 9, 20)
    start = today - timedelta(days=120)
    up = _series(start, 121, 1.0)            # +1/day
    spy = _series(start, 121, 0.2)           # +0.2/day
    down = _series(start, 121, -0.5, base=200)
    monkeypatch.setattr(md, "get_price_history", lambda tk, days=90: {"UPUP": up, "DOWN": down, "SPY": spy}[tk])
    d = today - timedelta(days=40)
    db.add_all([
        ModelCall(call_date=d, ticker="UPUP", direction="bullish", horizon_days=30, price_at_call=up[80]["close"]),
        ModelCall(call_date=d, ticker="DOWN", direction="bullish", horizon_days=30, price_at_call=down[80]["close"]),
        ModelCall(call_date=d + timedelta(days=1), ticker="DOWN", direction="bearish", horizon_days=90, price_at_call=down[81]["close"]),  # not due yet
    ])
    db.flush()
    assert md.resolve_calls(db, today) == 2
    rows = {(c.ticker, c.direction): c for c in db.query(ModelCall).filter(ModelCall.call_date >= d)}
    assert rows[("UPUP", "bullish")].outcome == "hit" and rows[("UPUP", "bullish")].excess_pct > 0
    assert rows[("DOWN", "bullish")].outcome == "miss"
    assert rows[("DOWN", "bearish")].resolved_at is None
    s = md.stats(db)
    assert s["resolved"] >= 2 and s["pending"] >= 1 and s["by_horizon"]["30"]["n"] >= 2
