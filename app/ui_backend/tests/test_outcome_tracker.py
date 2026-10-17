"""services.outcome_tracker — trading-day math, outcome labels, price lookup, gap detection."""

from datetime import date, timedelta

import pytest

from services import outcome_tracker as ot


class TestTradingDays:
    def test_skips_weekends(self):
        # Fri 2026-09-18 + 1 trading day = Mon 2026-09-21
        assert ot._add_trading_days(date(2026, 9, 18), 1) == date(2026, 9, 21)

    def test_five_trading_days_is_one_week(self):
        assert ot._add_trading_days(date(2026, 9, 14), 5) == date(2026, 9, 21)

    def test_zero(self):
        assert ot._add_trading_days(date(2026, 9, 16), 0) == date(2026, 9, 16)


class TestOutcomeLabel:
    @pytest.mark.parametrize("pct, label", [
        (5.0, "UP"), (2.0, "UP"), (1.99, "FLAT"), (0, "FLAT"), (-1.99, "FLAT"), (-2.0, "DOWN"), (-10, "DOWN"),
    ])
    def test_thresholds(self, pct, label):
        assert ot._outcome_label(pct) == label


class TestPriceOnDate:
    HIST = [
        {"date": "2026-09-14", "close": 100.0},
        {"date": "2026-09-15", "close": 101.0},
        {"date": "2026-09-18", "close": 103.0},   # 16th/17th missing (holiday)
    ]

    def test_exact(self):
        assert ot._price_on_date(self.HIST, date(2026, 9, 15)) == 101.0

    def test_nearest_before_when_missing(self):
        assert ot._price_on_date(self.HIST, date(2026, 9, 17)) == 101.0

    def test_after_last_bar_uses_last(self):
        assert ot._price_on_date(self.HIST, date(2026, 9, 30)) == 103.0

    def test_before_first_bar(self):
        assert ot._price_on_date(self.HIST, date(2026, 9, 1)) is None

    def test_ignores_bad_rows(self):
        assert ot._price_on_date([{"date": "n/a", "close": 1}] + self.HIST, date(2026, 9, 14)) == 100.0


class TestDetectSnapshotGaps:
    def test_weekdays_without_a_snapshot_are_gaps(self, db, monkeypatch):
        from models.signal_outcome import SignalOutcome
        db.query(SignalOutcome).delete()
        # Snapshot exists for every weekday in the window except one.
        today = date(2026, 9, 18)   # a Friday
        monkeypatch.setattr(ot, "_market_today", lambda: today)
        missing = date(2026, 9, 15)
        d = today - timedelta(days=7)
        while d <= today:   # the window is inclusive of both ends
            if d.weekday() < 5 and d != missing:
                db.add(SignalOutcome(ticker="AAPL", signal_date=d, composite_score=50, price_at_signal=1.0))
            d += timedelta(days=1)
        db.flush()
        gaps = ot.detect_snapshot_gaps(db, window_days=7)
        assert gaps == [missing]


class TestMarketToday:
    def test_uses_new_york_date_not_utc(self, monkeypatch):
        """22:41 ET on Oct 5 is already Oct 6 in UTC — the container's clock."""
        from datetime import datetime, timezone
        utc_late = datetime(2026, 10, 6, 2, 41, tzinfo=timezone.utc)

        class _DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return utc_late.astimezone(tz) if tz else utc_late
        monkeypatch.setattr(ot, "datetime", _DT)
        assert ot._market_today() == date(2026, 10, 5)


class TestSnapshotRowsArePlainPython:
    def test_numpy_scores_and_price_are_converted(self, monkeypatch):
        """One numpy scalar made psycopg2 emit `np.float64(…)` and fail the batch."""
        import numpy as np
        import routers.signals as rs
        payload = {"score_version": 3, "signals": [{
            "ticker": "NVDA", "current_price": np.float64(228.38),
            "composite_score": np.int64(71), "label": "Buy", "signal": "BUY",
            "sub_scores": {"smart_money": np.float64(20.5), "insider": 10, "corporate": 5,
                           "momentum": np.float64(12.0), "sentiment": 50, "risk_penalty": 0},
        }]}
        monkeypatch.setattr(rs, "technical_signals", lambda db: payload)
        monkeypatch.setattr(ot, "_politician_by_ticker", lambda db, tickers: {})
        captured = {}

        class _Result:
            rowcount = 1

        class _DB:
            def execute(self, stmt):
                captured["rows"] = stmt.compile().params
                return _Result()
            def commit(self):
                pass

        monkeypatch.setattr(ot, "_market_today", lambda: date(2026, 10, 5))
        assert ot.snapshot_signals(_DB()) == 1
        values = [v for k, v in captured["rows"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        assert values, captured["rows"]
        for v in values:
            assert type(v) in (int, float), (v, type(v))


class _FrozenDate(date):
    """date subclass whose today() is fixed — the module does `from datetime import date`."""
    _today = None
    def __new__(cls, fixed):
        cls._today = fixed
        return date.__new__(cls, fixed.year, fixed.month, fixed.day)
    @classmethod
    def today(cls):
        return cls._today


class TestExcessVsSpy:
    """Raw win rate vs. beating the market over the same days."""

    @staticmethod
    def _spy(start: date, days: int, start_px: float, step: float) -> list[dict]:
        out, d, px = [], start, start_px
        for _ in range(days):
            if d.weekday() < 5:
                out.append({"date": d.isoformat(), "close": round(px, 4)})
                px += step
            d += timedelta(days=1)
        return out

    def test_flat_market_excess_equals_return(self):
        spy = self._spy(date(2026, 6, 1), 200, 500.0, 0.0)
        out = ot.excess_vs_spy([("Watch", date(2026, 6, 1), 5.0, None, None)], spy)
        assert out[("Watch", 30)] == {"avg_return": 5.0, "avg_excess": 5.0, "beat_spy_rate": 100.0, "spy_measured": 1}
        assert ("Watch", 60) not in out

    def test_rising_market_turns_a_win_into_a_loss(self):
        # SPY +1/day from 100 → +30% over 30 trading days; the signal's +10% lags it
        spy = self._spy(date(2026, 6, 1), 200, 100.0, 1.0)
        out = ot.excess_vs_spy([("Strong Watch", date(2026, 6, 1), 10.0, None, None)], spy)
        assert out[("Strong Watch", 30)]["avg_excess"] == -20.0
        assert out[("Strong Watch", 30)]["beat_spy_rate"] == 0.0

    def test_averages_and_rates_per_label_and_window(self):
        spy = self._spy(date(2026, 6, 1), 300, 500.0, 0.0)
        rows = [
            ("Neutral", date(2026, 6, 1), 4.0, -2.0, None),
            ("Neutral", date(2026, 6, 2), -6.0, 8.0, None),
        ]
        out = ot.excess_vs_spy(rows, spy)
        assert out[("Neutral", 30)]["avg_return"] == -1.0
        assert out[("Neutral", 30)]["beat_spy_rate"] == 50.0
        assert out[("Neutral", 60)]["avg_excess"] == 3.0

    def test_rows_older_than_spy_history_skip_the_spy_numbers(self):
        spy = self._spy(date(2026, 7, 1), 200, 500.0, 0.0)
        out = ot.excess_vs_spy([("Watch", date(2026, 6, 1), 5.0, None, None)], spy)
        assert out[("Watch", 30)] == {"avg_return": 5.0, "avg_excess": None, "beat_spy_rate": None, "spy_measured": 0}
