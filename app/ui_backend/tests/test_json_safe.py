"""A NaN anywhere in a payload used to 500 the whole endpoint.

Production, 2026-09-23: /signals/, /watchlist/signals, /ai-desk/today and
/market/performance failed together 32 times in a day on
``ValueError: Out of range float values are not JSON compliant``.
"""

import json
import math

from json_safe import SafeJSONResponse, scrub_non_finite


def test_finite_payload_is_untouched():
    payload = {"a": 1.5, "b": [1, 2, 3], "c": {"d": "text"}, "e": None, "f": True}
    cleaned, found = scrub_non_finite(payload)
    assert cleaned == payload
    assert found == []


def test_nan_and_infinities_become_null():
    payload = {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")}
    cleaned, found = scrub_non_finite(payload)
    assert cleaned == {"nan": None, "inf": None, "ninf": None}
    assert len(found) == 3


def test_reports_where_it_found_them():
    payload = {"signals": [{"ticker": "ABC", "score": float("nan")}]}
    _, found = scrub_non_finite(payload)
    assert found == ["$.signals[0].score=nan"]


def test_booleans_are_not_mistaken_for_floats():
    cleaned, found = scrub_non_finite({"ok": True, "no": False})
    assert cleaned == {"ok": True, "no": False}
    assert found == []


def test_response_renders_instead_of_raising():
    body = SafeJSONResponse({"score": float("nan"), "name": "ABC"}).render(
        {"score": float("nan"), "name": "ABC"}
    )
    assert json.loads(body) == {"score": None, "name": "ABC"}


def test_response_is_byte_identical_for_clean_payloads():
    payload = {"b": 2, "a": [1.0, None, "x"]}
    assert SafeJSONResponse(payload).render(payload) == json.dumps(
        payload, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
    ).encode("utf-8")


def test_a_real_nan_still_fails_json_dumps_without_the_fix():
    # Guards the premise: this is the error seen in production.
    try:
        json.dumps({"x": math.nan}, allow_nan=False)
    except ValueError as exc:
        assert "not JSON compliant" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected json.dumps to reject NaN")
