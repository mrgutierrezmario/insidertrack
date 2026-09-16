"""
Unit tests for pagination logic (has_more, offset/limit arithmetic).
"""

import pytest


# ── has_more logic (used by trades, insiders, fed/trades, etc.) ──────────────

class TestHasMoreLogic:
    """The +1 fetch pattern: fetch limit+1 rows, has_more = len > limit, slice to limit."""

    def _paginate(self, all_rows, offset, limit):
        """Simulate the +1 fetch pagination used across the app."""
        window = all_rows[offset: offset + limit + 1]
        has_more = len(window) > limit
        page = window[:limit]
        return page, has_more

    def test_first_page_no_more(self):
        rows = list(range(5))
        page, has_more = self._paginate(rows, offset=0, limit=10)
        assert page == [0, 1, 2, 3, 4]
        assert has_more is False

    def test_first_page_has_more(self):
        rows = list(range(15))
        page, has_more = self._paginate(rows, offset=0, limit=10)
        assert page == list(range(10))
        assert has_more is True

    def test_second_page_no_more(self):
        rows = list(range(15))
        page, has_more = self._paginate(rows, offset=10, limit=10)
        assert page == [10, 11, 12, 13, 14]
        assert has_more is False

    def test_exact_page_boundary(self):
        rows = list(range(10))
        page, has_more = self._paginate(rows, offset=0, limit=10)
        assert len(page) == 10
        assert has_more is False

    def test_one_over_page_boundary(self):
        rows = list(range(11))
        page, has_more = self._paginate(rows, offset=0, limit=10)
        assert len(page) == 10
        assert has_more is True

    def test_empty_result(self):
        page, has_more = self._paginate([], offset=0, limit=10)
        assert page == []
        assert has_more is False

    def test_offset_beyond_end(self):
        rows = list(range(5))
        page, has_more = self._paginate(rows, offset=10, limit=10)
        assert page == []
        assert has_more is False


# ── Risk-filter over-fetch pagination ─────────────────────────────────────────

class TestRiskFilterPagination:
    """
    When a risk_level filter is active, list_trades over-fetches and filters
    in Python. The slice/has_more logic should still be correct.
    """

    def _filter_page(self, filtered_rows, offset, limit):
        page = filtered_rows[offset: offset + limit]
        has_more = len(filtered_rows) > offset + limit
        return page, has_more

    def test_single_page(self):
        rows = list(range(3))
        page, has_more = self._filter_page(rows, offset=0, limit=10)
        assert page == [0, 1, 2]
        assert has_more is False

    def test_has_more_true(self):
        rows = list(range(25))
        page, has_more = self._filter_page(rows, offset=0, limit=10)
        assert len(page) == 10
        assert has_more is True

    def test_second_page_correct(self):
        rows = list(range(25))
        page, has_more = self._filter_page(rows, offset=10, limit=10)
        assert page == list(range(10, 20))
        assert has_more is True

    def test_last_page_no_more(self):
        rows = list(range(25))
        page, has_more = self._filter_page(rows, offset=20, limit=10)
        assert page == [20, 21, 22, 23, 24]
        assert has_more is False


# ── Query bound validation ────────────────────────────────────────────────────

class TestQueryBounds:
    """Verify the ge/le constraint semantics used on list endpoints."""

    @pytest.mark.parametrize("limit,valid", [
        (0, False),
        (-1, False),
        (1, True),
        (100, True),
        (500, True),
        (501, False),
    ])
    def test_limit_bounds(self, limit, valid):
        # Mirrors Query(ge=1, le=500) semantics
        assert valid == (1 <= limit <= 500)

    @pytest.mark.parametrize("days,valid", [
        (0, False),
        (-1, False),
        (1, True),
        (90, True),
        (365, True),
        (366, False),
    ])
    def test_days_bounds(self, days, valid):
        # Mirrors Query(ge=1, le=365) used by GET /market/history/{ticker}
        assert valid == (1 <= days <= 365)
