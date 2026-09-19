"""Daily cap on site-key AI generations."""

from config import settings
from services import ai_summary as ai


def test_cap_counts_only_site_spend(monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_cap", 2)
    ai._daily.update(day=None, count=0)
    assert ai._site_budget_ok()
    ai._site_budget_spend(); ai._site_budget_spend()
    assert not ai._site_budget_ok()


def test_cap_resets_on_new_day(monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_cap", 1)
    ai._daily.update(day="1999-01-01", count=99)
    assert ai._site_budget_ok()          # a new UTC day zeroes the counter
    assert ai._daily["count"] == 0
