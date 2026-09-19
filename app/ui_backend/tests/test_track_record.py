"""services.track_record — entry/exit math and aggregates on synthetic prices."""

from datetime import date, timedelta

from services import track_record as tr


def _series(start: date, n: int, step: float, base: float = 100.0):
    return [{"date": (start + timedelta(days=i)).isoformat(), "close": round(base + i * step, 2)} for i in range(n)]


class TestPriceLookups:
    def test_entry_is_first_close_on_or_after(self):
        h = [{"date": "2026-01-05", "close": 10}, {"date": "2026-01-07", "close": 11}]
        assert tr._close_on_or_after(h, date(2026, 1, 6)) == (date(2026, 1, 7), 11.0)
        assert tr._close_on_or_after(h, date(2026, 2, 1)) is None

    def test_exit_is_last_close_on_or_before(self):
        h = [{"date": "2026-01-05", "close": 10}, {"date": "2026-01-07", "close": 11}]
        assert tr._close_on_or_before(h, date(2026, 1, 6)) == 10.0
        assert tr._close_on_or_before(h, date(2026, 1, 1)) is None

    def test_bucket(self):
        assert tr._bucket(30) == 200 and tr._bucket(201) == 400 and tr._bucket(9999) == 1600


class TestComputeTrackRecord:
    def test_returns_and_excess(self, db, monkeypatch):
        from models.politician import Politician
        from models.trade import Trade
        p = Politician(name="Rep Record", chamber="house"); db.add(p); db.flush()
        today = date.today()
        disclosed = today - timedelta(days=100)
        db.add_all([
            Trade(politician_id=p.id, ticker="UPUP", transaction_type="purchase", direction="buy", asset_type="stock",
                  amount_range="$1,001 - $15,000", trade_date=disclosed - timedelta(days=10), disclosure_date=disclosed,
                  source="house", raw_data="{}"),
            # an option and a sale must be ignored
            Trade(politician_id=p.id, ticker="UPUP", transaction_type="purchase", direction="buy", asset_type="option",
                  amount_range="$1,001 - $15,000", trade_date=disclosed, disclosure_date=disclosed, source="house", raw_data="{}"),
            Trade(politician_id=p.id, ticker="UPUP", transaction_type="sale", direction="sell", asset_type="stock",
                  amount_range="$1,001 - $15,000", trade_date=disclosed, disclosure_date=disclosed, source="house", raw_data="{}"),
        ])
        db.flush()
        start = today - timedelta(days=400)
        # UPUP rises $1/day from 100; SPY rises $0.5/day from 100.
        series = {"UPUP": _series(start, 401, 1.0), "SPY": _series(start, 401, 0.5)}
        monkeypatch.setattr(tr, "get_price_history", lambda tk, days=90: series[tk])
        monkeypatch.setattr(tr, "cache_get", lambda k: None)
        monkeypatch.setattr(tr, "cache_set", lambda k, v, ttl: None)

        out = tr.compute_track_record(db, p.id)
        assert out["evaluated"] == 1
        (row,) = out["trades"]
        entry = 100 + (disclosed - start).days
        assert row["entry_price"] == entry
        assert row["r30"] == round(30 / entry * 100, 2)
        assert row["x30"] is not None and row["x30"] > 0          # beat SPY
        w30 = out["windows"]["30"]
        assert w30["n"] == 1 and w30["win_rate"] == 100.0 and w30["beat_spy_rate"] == 100.0

    def test_demo_prices_are_skipped(self, db, monkeypatch):
        from models.politician import Politician
        from models.trade import Trade
        p = Politician(name="Rep Demo", chamber="house"); db.add(p); db.flush()
        d = date.today() - timedelta(days=60)
        db.add(Trade(politician_id=p.id, ticker="FAKE", transaction_type="purchase", direction="buy", asset_type="stock",
                     amount_range="$1,001 - $15,000", trade_date=d, disclosure_date=d, source="house", raw_data="{}"))
        db.flush()
        monkeypatch.setattr(tr, "get_price_history", lambda tk, days=90: [{"date": d.isoformat(), "close": 1, "_demo": True}])
        monkeypatch.setattr(tr, "cache_get", lambda k: None)
        monkeypatch.setattr(tr, "cache_set", lambda k, v, ttl: None)
        out = tr.compute_track_record(db, p.id)
        assert out["evaluated"] == 0 and out["skipped_demo"] == 1
