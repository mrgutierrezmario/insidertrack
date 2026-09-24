"""
Unit tests for market_data helpers that don't require external APIs.
"""

import time
import pytest


class TestCacheEviction:
    """_cache_set evicts expired entries when the dict grows beyond 500."""

    def test_cache_get_hit(self):
        from services.market_data import _cache_set, _cache_get, _cache, CACHE_TTL
        _cache_set("test:evict:hit", {"v": 1})
        assert _cache_get("test:evict:hit") == {"v": 1}

    def test_cache_get_miss_after_ttl(self, monkeypatch):
        from services import market_data, persistent_cache
        from services.market_data import _cache_set, _cache_get
        _cache_set("test:evict:expired", {"v": 99})
        # Advance time past TTL so the L1 entry appears expired
        original = time.time()
        monkeypatch.setattr("services.market_data.time", type("t", (), {
            "time": staticmethod(lambda: original + market_data.CACHE_TTL + 1)
        })())
        # Mock L2 to also miss — the test is about L1 TTL, not L2 hydration
        monkeypatch.setattr(persistent_cache, "cache_get", lambda _k: None)
        result = _cache_get("test:evict:expired")
        assert result is None

    def test_eviction_runs_when_over_limit(self):
        from services.market_data import _cache_set, _cache, CACHE_TTL
        # Pre-expire the existing keys (per-entry TTL stored in the 3-tuple)
        now = time.time()
        for i in range(510):
            _cache[f"test:bulk:{i}"] = (now - 999, f"val{i}", CACHE_TTL)
        # This call should trigger eviction
        _cache_set("test:evict:trigger", "new")
        assert len(_cache) < 510


class TestDemoHistory:
    def test_returns_correct_length(self):
        from services.market_data import _demo_history
        result = _demo_history("AAPL", 30)
        assert len(result) == 30

    def test_bars_have_required_keys(self):
        from services.market_data import _demo_history
        result = _demo_history("NVDA", 10)
        for bar in result:
            assert "date" in bar
            assert "open" in bar
            assert "high" in bar
            assert "low" in bar
            assert "close" in bar
            assert "volume" in bar
            assert bar["_demo"] is True

    def test_ohlc_consistency(self):
        from services.market_data import _demo_history
        for bar in _demo_history("SPY", 60):
            assert bar["low"] <= bar["close"] <= bar["high"]
            assert bar["low"] <= bar["open"] <= bar["high"]
            assert bar["close"] > 0

    def test_unknown_ticker_uses_default_seed(self):
        from services.market_data import _demo_history
        bars = _demo_history("ZZZNONE", 5)
        assert len(bars) == 5
        assert all(b["close"] > 0 for b in bars)

    def test_deterministic_for_same_ticker(self):
        from services.market_data import _demo_history
        assert _demo_history("AAPL", 10) == _demo_history("AAPL", 10)


class TestGetCurrentPriceMeta:
    def test_with_meta_false_returns_float(self, monkeypatch):
        import services.market_data as md
        monkeypatch.setattr(md, "yf", type("yf", (), {
            "Ticker": lambda self, t: type("T", (), {
                "fast_info": type("fi", (), {"last_price": 123.45})()
            })()
        })())
        result = md.get_current_price("AAPL", with_meta=False)
        assert isinstance(result, float)

    def test_with_meta_true_returns_dict(self, monkeypatch):
        import services.market_data as md
        monkeypatch.setattr(md, "yf", type("yf", (), {
            "Ticker": lambda self, t: type("T", (), {
                "fast_info": type("fi", (), {"last_price": 150.0})()
            })()
        })())
        result = md.get_current_price("AAPL", with_meta=True)
        assert isinstance(result, dict)
        assert "price" in result
        assert "is_demo" in result
        assert result["is_demo"] is False

    def test_fallback_sets_is_demo_true(self, monkeypatch):
        import services.market_data as md

        # Both live sources unavailable: yfinance raises, Yahoo-direct returns None.
        monkeypatch.setattr(md, "yf", type("yf", (), {"Ticker": lambda self, t: (_ for _ in ()).throw(RuntimeError("bad"))})())
        monkeypatch.setattr(md, "_yahoo_price", lambda t: None)

        result = md.get_current_price("AAPL", with_meta=True)
        # With no live source, should fall back to the demo price.
        assert result["is_demo"] is True
        assert result["price"] > 0

    def test_yahoo_fallback_used_when_yfinance_fails(self, monkeypatch):
        import services.market_data as md

        # yfinance down, but Yahoo-direct returns a real price → not demo.
        monkeypatch.setattr(md, "yf", type("yf", (), {"Ticker": lambda self, t: (_ for _ in ()).throw(RuntimeError("bad"))})())
        monkeypatch.setattr(md, "_yahoo_price", lambda t: 287.5)

        result = md.get_current_price("AAPL", with_meta=True)
        assert result == {"price": 287.5, "is_demo": False}


class TestYahooParsers:
    """Parsing of the Yahoo chart payload into history / intraday rows.
    _yahoo_chart (the network call) is monkeypatched with a canned result."""

    def _fake_result(self):
        now = int(time.time())
        return {
            "meta": {"gmtoffset": -14400, "fiftyTwoWeekHigh": 320.0, "fiftyTwoWeekLow": 190.0},
            "timestamp": [now - 86400, now],
            "indicators": {"quote": [{
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.5],
                "close": [101.5, None],   # second bar has a null close → skipped
                "volume": [1000, 2000],
            }]},
        }

    def test_history_parses_and_skips_nulls(self, monkeypatch):
        import services.market_data as md
        monkeypatch.setattr(md, "_yahoo_chart", lambda *a, **k: self._fake_result())
        rows = md._yahoo_history("AAPL", 90)
        assert len(rows) == 1                       # null-close bar dropped
        assert rows[0]["close"] == 101.5
        assert set(rows[0]) == {"date", "open", "high", "low", "close", "volume"}

    def test_history_none_when_no_result(self, monkeypatch):
        import services.market_data as md
        monkeypatch.setattr(md, "_yahoo_chart", lambda *a, **k: None)
        assert md._yahoo_history("AAPL", 90) is None

    def test_intraday_formats_local_time(self, monkeypatch):
        import services.market_data as md
        monkeypatch.setattr(md, "_yahoo_chart", lambda *a, **k: self._fake_result())
        candles = md._yahoo_intraday("AAPL", "5min")
        assert len(candles) == 1
        # "YYYY-MM-DD HH:MM:SS" shape the chart's toChartTime expects
        assert len(candles[0]["time"]) == 19 and candles[0]["time"][10] == " "
        assert candles[0]["close"] == 101.5

    def test_intraday_interval_mapping(self, monkeypatch):
        import services.market_data as md
        captured = {}
        def fake_chart(ticker, range_="1d", interval="1d"):
            captured["interval"] = interval
            return self._fake_result()
        monkeypatch.setattr(md, "_yahoo_chart", fake_chart)
        md._yahoo_intraday("AAPL", "15min")
        assert captured["interval"] == "15m"


class TestYfinanceHistorySkipsNaNRows:
    """yfinance carries holidays and halts as NaN, not None.

    One NaN row used to reach closes[-1] (a ticker's current_price), every
    SMA computed over it, and the L2 cache — where Postgres rejects NaN in a
    `json` column, so the write failed and the ticker was re-fetched on every
    request. Production, 2026-09-23: 202 non-finite floats in one /signals/
    response and ~200 failed cache writes in twenty minutes.
    """

    def _frame(self):
        import pandas as pd

        return pd.DataFrame(
            {
                "Open": [10.0, float("nan"), 12.0],
                "High": [11.0, float("nan"), 13.0],
                "Low": [9.0, float("nan"), 11.0],
                "Close": [10.5, float("nan"), 12.5],
                # Volume stays valid on purpose: that is the production shape.
                # With Volume NaN too, int(nan) raises inside the branch and
                # the whole yfinance path falls back to demo data — so the
                # bug would never reach the assertions.
                "Volume": [1000, 1100, 1200],
            },
            index=pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"]),
        )

    def test_nan_rows_are_dropped(self, monkeypatch):
        import services.market_data as md

        monkeypatch.setattr(md, "_history_cache_get", lambda _k: None)
        monkeypatch.setattr(md, "_history_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(md, "_yf_call", lambda *a, **k: self._frame())

        rows = md.get_price_history("TEST", days=30)

        assert [r["date"] for r in rows] == ["2026-09-21", "2026-09-23"]
        assert all(
            v == v  # NaN is the only value not equal to itself
            for r in rows
            for v in (r["open"], r["high"], r["low"], r["close"])
        )

    def test_result_survives_json_round_trip(self, monkeypatch):
        """What the L2 cache does. NaN would raise here, as Postgres does."""
        import json

        import services.market_data as md

        monkeypatch.setattr(md, "_history_cache_get", lambda _k: None)
        monkeypatch.setattr(md, "_history_cache_set", lambda *a, **k: None)
        monkeypatch.setattr(md, "_yf_call", lambda *a, **k: self._frame())

        rows = md.get_price_history("TEST", days=30)
        assert json.loads(json.dumps(rows, allow_nan=False)) == rows
