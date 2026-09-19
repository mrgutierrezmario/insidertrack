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
        monkeypatch.setattr(ot, "date", _FrozenDate(today))
        missing = date(2026, 9, 15)
        d = today - timedelta(days=7)
        while d <= today:   # the window is inclusive of both ends
            if d.weekday() < 5 and d != missing:
                db.add(SignalOutcome(ticker="AAPL", signal_date=d, composite_score=50, price_at_signal=1.0))
            d += timedelta(days=1)
        db.flush()
        gaps = ot.detect_snapshot_gaps(db, window_days=7)
        assert gaps == [missing]


class _FrozenDate(date):
    """date subclass whose today() is fixed — the module does `from datetime import date`."""
    _today = None
    def __new__(cls, fixed):
        cls._today = fixed
        return date.__new__(cls, fixed.year, fixed.month, fixed.day)
    @classmethod
    def today(cls):
        return cls._today
