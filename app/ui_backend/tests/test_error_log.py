from services import error_log as el


def test_record_and_summary():
    el._events.clear()
    el.record("ZeroDivisionError", "GET /signals/", "abc")
    el.record("KeyError", "GET /x", "def")
    s = el.summary(24)
    assert s["count"] == 2 and s["by_type"] == {"ZeroDivisionError": 1, "KeyError": 1}
    assert s["latest"][-1]["rid"] == "def"
