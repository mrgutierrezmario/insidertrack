"""services.source_health — per-source freshness bookkeeping."""

from datetime import datetime, timedelta, timezone

import pytest

from services import source_health as sh


@pytest.fixture(autouse=True)
def _clean(db):
    from models.app_setting import AppSetting
    db.query(AppSetting).filter(AppSetting.key.like("source_health:%")).delete(synchronize_session=False)
    db.commit()
    yield


class TestRecordAndSummary:
    def test_never_run(self, db):
        s = sh.summary(db)
        assert s["status"] == "ok"
        assert s["sources"]["senate"]["status"] == "never"

    def test_success_with_rows_is_ok(self, db):
        sh.record(db, "senate", ok=True, new_rows=12)
        src = sh.summary(db)["sources"]["senate"]
        assert src["status"] == "ok"
        assert src["last_new_rows"] == 12
        assert src["last_new_rows_at"] is not None
        assert src["consecutive_failures"] == 0

    def test_failures_accumulate_then_flip_to_failing(self, db):
        for _ in range(sh.FAILING_AFTER - 1):
            sh.record(db, "house", ok=False, error="boom")
        assert sh.summary(db)["sources"]["house"]["status"] == "ok"
        sh.record(db, "house", ok=False, error="boom")
        src = sh.summary(db)["sources"]["house"]
        assert src["status"] == "failing"
        assert src["last_error"] == "boom"
        assert sh.summary(db)["status"] == "failing"

    def test_success_resets_failure_streak(self, db):
        for _ in range(sh.FAILING_AFTER):
            sh.record(db, "house", ok=False, error="boom")
        sh.record(db, "house", ok=True, new_rows=0)
        src = sh.summary(db)["sources"]["house"]
        assert src["consecutive_failures"] == 0 and src["status"] == "ok"

    def test_quiet_source_is_stale(self, db, monkeypatch):
        sh.record(db, "form4", ok=True, new_rows=5)
        # runs keep succeeding but produce nothing for longer than the window
        later = datetime.now(timezone.utc) + timedelta(days=sh.SOURCES["form4"]["max_quiet_days"] + 1)
        monkeypatch.setattr(sh, "_now", lambda: later)
        sh.record(db, "form4", ok=True, new_rows=0)
        src = sh.summary(db)["sources"]["form4"]
        assert src["status"] == "stale"
        assert src["last_new_rows_at"] < src["last_success_at"]
        assert [p["source"] for p in sh.problems(db)] == ["form4"]

    def test_zero_rows_inside_window_is_fine(self, db):
        sh.record(db, "senate", ok=True, new_rows=3)
        sh.record(db, "senate", ok=True, new_rows=0)
        assert sh.summary(db)["sources"]["senate"]["status"] == "ok"
