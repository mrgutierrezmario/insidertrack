"""services.late_filing — the 45-day rule and the late-filers ranking."""

from datetime import date, timedelta

from services import late_filing as lf


class TestRule:
    def test_45_days_is_on_time_46_is_late(self):
        t = date(2026, 1, 1)
        assert not lf.is_late(t, t + timedelta(days=45))
        assert lf.is_late(t, t + timedelta(days=46))

    def test_missing_dates_are_not_late(self):
        assert not lf.is_late(None, date(2026, 1, 1))
        assert not lf.is_late(date(2026, 1, 1), None)
        assert lf.lag_days(None, None) is None


def _trade(pid, traded, disclosed, filing="F1", source="house"):
    from models.trade import Trade
    return Trade(politician_id=pid, ticker="LATE", transaction_type="purchase", direction="buy", asset_type="stock",
                 amount_range="$1,001 - $15,000", trade_date=traded, disclosure_date=disclosed,
                 source=source, filing_id=filing, raw_data="{}")


class TestLateFilers:
    def _seed(self, db):
        from models.politician import Politician
        slow = Politician(name="LF Slow", chamber="house", party="R", state="TX")
        prompt = Politician(name="LF Prompt", chamber="senate")
        once = Politician(name="LF Once", chamber="house")
        db.add_all([slow, prompt, once]); db.flush()
        d = date(2026, 6, 1)
        db.add_all([
            # Slow: 3 of 4 late across two filings; worst is 200 days
            _trade(slow.id, d - timedelta(days=60), d, "A"),
            _trade(slow.id, d - timedelta(days=90), d, "A"),
            _trade(slow.id, d - timedelta(days=200), d, "B"),
            _trade(slow.id, d - timedelta(days=10), d, "C"),
            # Prompt: never late
            _trade(prompt.id, d - timedelta(days=30), d, "uuid-1", "senate"),
            # Once: one late trade, disclosed long ago
            _trade(once.id, date(2020, 1, 1), date(2020, 6, 1), "Z"),
        ])
        db.flush()
        return slow, prompt, once

    def _mine(self, out):
        return {r["name"]: r for r in out["items"] if r["name"].startswith("LF ")}

    def test_ranks_members_by_late_trades(self, db):
        self._seed(db)
        mine = self._mine(lf.late_filers(db))
        assert set(mine) == {"LF Slow", "LF Once"}       # Prompt filed on time
        s = mine["LF Slow"]
        assert (s["trades"], s["late_trades"], s["late_pct"], s["late_filings"]) == (4, 3, 75.0, 2)
        assert s["median_lag_days"] == 90
        assert s["worst"]["lag_days"] == 200 and s["worst"]["disclosure_date"] == "2026-06-01"
        assert s["worst"]["filing_url"].endswith("/2026/B.pdf")
        names = [r["name"] for r in lf.late_filers(db)["items"]]
        assert names.index("LF Slow") < names.index("LF Once")

    def test_window_counts_only_recent_disclosures(self, db):
        self._seed(db)
        mine = self._mine(lf.late_filers(db, days=365, today=date(2026, 10, 1)))
        assert set(mine) == {"LF Slow"}

    def test_endpoint(self, db):
        from fastapi.testclient import TestClient
        from main import app
        from database import get_db
        self._seed(db)
        app.dependency_overrides[get_db] = lambda: db
        try:
            r = TestClient(app).get("/politicians/late-filers?limit=500")
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert r.status_code == 200
        body = r.json()
        assert body["late_after_days"] == 45 and body["window_days"] is None
        assert "LF Slow" in [x["name"] for x in body["items"]]
