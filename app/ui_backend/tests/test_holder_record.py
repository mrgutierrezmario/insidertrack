"""services.holder_record — 13F positions measured from the public filing date."""

from datetime import date, timedelta

from services import holder_record as hr


def _series(start: date, n: int, step: float, base: float = 100.0):
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": round(base + i * step, 2)} for i in range(n)]


def test_buys_and_sells_measured_from_filed_on(db, monkeypatch):
    from models.whale import WhaleHolder, WhalePosition
    h = WhaleHolder(name="Rec Fund", cik="0000000099", is_tracked=True); db.add(h); db.flush()
    today = date.today()
    q_end = today - timedelta(days=150)
    filed = q_end + timedelta(days=40)
    db.add_all([
        WhalePosition(holder_id=h.id, ticker="UPUP", company_name="Up", value_usd=5_000_000, filing_date=q_end, filed_on=filed, quarter="2026-Q1", change_type="new"),
        WhalePosition(holder_id=h.id, ticker="DOWN", company_name="Down", value_usd=1_000_000, filing_date=q_end, filed_on=filed, quarter="2026-Q1", change_type="closed"),
        WhalePosition(holder_id=h.id, ticker="INIT", company_name="Init", value_usd=1_000_000, filing_date=q_end, filed_on=filed, quarter="2026-Q1", change_type="initial"),
        WhalePosition(holder_id=h.id, ticker="UPUP", company_name="Up (class B)", value_usd=100, filing_date=q_end, filed_on=filed, quarter="2026-Q1", change_type="new"),
    ])
    db.flush()
    start = today - timedelta(days=400)
    series = {"UPUP": _series(start, 401, 1.0), "DOWN": _series(start, 401, -0.3, base=200), "SPY": _series(start, 401, 0.2)}
    monkeypatch.setattr(hr, "get_price_history", lambda tk, days=90: series[tk])
    monkeypatch.setattr(hr, "cache_get", lambda k: None)
    monkeypatch.setattr(hr, "cache_set", lambda k, v, ttl: None)
    out = hr.compute_holder_record(db, h.id)
    assert out["buys"]["evaluated"] == 1 and out["sells"]["evaluated"] == 1      # "initial" skipped; duplicate UPUP row folded
    b = out["buys"]["trades"][0]
    assert b["public_on"] == filed.isoformat()                                     # measured from the filing date, not quarter end
    assert out["buys"]["windows"]["90"]["beat_spy_rate"] == 100.0
    assert out["sells"]["windows"]["90"]["beat_spy_rate"] == 100.0                # the closed position then lagged SPY → good call


def test_leaderboard_uses_longest_window_with_data(db, monkeypatch):
    from models.whale import WhaleHolder
    h = WhaleHolder(name="Young Fund", cik="0000000098", is_tracked=True); db.add(h); db.flush()
    rec = {"buys": {"windows": {
        "30": {"n": 12, "beat_spy_rate": 58.3, "avg_excess": 1.1},
        "60": {"n": 0, "beat_spy_rate": None, "avg_excess": None},
        "90": {"n": 0, "beat_spy_rate": None, "avg_excess": None}}}}
    monkeypatch.setattr(hr, "cache_get", lambda k: (rec,) if k == f"holder_record:{h.id}:v2" else None)
    row = next(r for r in hr.holder_leaderboard(db) if r["id"] == h.id)
    assert row["window"] == 30 and row["n"] == 12 and row["beat_spy_rate"] == 58.3
