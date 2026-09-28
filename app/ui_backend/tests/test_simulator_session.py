"""The simulator closes its database session before fetching prices (so a
hung fetch can't hold a transaction open) and must still answer correctly,
including the member's name, which lives on a related row."""

from datetime import date
from unittest.mock import patch

import pytest

from models.politician import Politician
from models.trade import Trade
from routers.simulator import growth_simulation, project_investment


@pytest.fixture()
def entry(db):
    db.query(Trade).delete()
    db.query(Politician).delete()
    p = Politician(name="Test Member", chamber="House", is_tracked=True)
    db.add(p)
    db.flush()
    db.add(Trade(politician_id=p.id, ticker="ABC", direction="buy", disclosure_date=date(2026, 1, 5)))
    db.commit()
    yield
    db.query(Trade).delete()
    db.query(Politician).delete()
    db.commit()


HISTORY = [
    {"date": "2026-01-02", "close": 9.0},
    {"date": "2026-01-05", "close": 10.0},
    {"date": "2026-02-02", "close": 12.0},
]


def test_project_after_closing_the_session(db, entry):
    with (
        patch("routers.simulator.get_price_history", return_value=HISTORY),
        patch("routers.simulator.get_current_price", return_value={"price": 15.0, "is_demo": False}),
    ):
        r = project_investment(ticker="abc", amount=100.0, db=db)
    assert r["entry_price"] == 10.0 and r["current_value"] == 150.0
    assert r["triggered_by"] == "Test Member"


def test_growth_after_closing_the_session(db, entry):
    with patch("routers.simulator.get_price_history", return_value=HISTORY):
        r = growth_simulation(ticker="ABC", amount=100.0, db=db)
    assert r["entry_date"] == "2026-01-05"
    assert r["points"][-1]["value"] == 120.0
    assert r["triggered_by"] == "Test Member"


def test_both_views_agree_on_the_entry_day_and_load_enough_history(db, entry):
    # Disclosed on a Monday holiday: the first trading day after is the entry.
    history = [{"date": "2026-01-06", "close": 20.0}, {"date": "2026-02-02", "close": 30.0}]
    asked = []

    def fake_history(ticker, days):
        asked.append(days)
        return history

    with (
        patch("routers.simulator.get_price_history", side_effect=fake_history),
        patch("routers.simulator.get_current_price", return_value={"price": 30.0, "is_demo": False}),
    ):
        p = project_investment(ticker="ABC", amount=100.0, db=db)
        g = growth_simulation(ticker="ABC", amount=100.0, db=db)
    assert p["entry_date"] == g["entry_date"] == "2026-01-06"
    assert p["disclosure_date"] == g["disclosure_date"] == "2026-01-05"
    # Always reaches back past the disclosure, and never less than a year.
    since = (date.today() - date(2026, 1, 5)).days
    assert all(d >= max(365, since) for d in asked)


def test_an_old_disclosure_asks_for_more_than_a_year(db):
    db.query(Trade).delete()
    db.query(Politician).delete()
    p = Politician(name="Old Buyer", chamber="Senate", is_tracked=True)
    db.add(p)
    db.flush()
    db.add(Trade(politician_id=p.id, ticker="OLD", direction="buy", disclosure_date=date(2021, 8, 13)))
    db.commit()
    asked = []

    def fake_history(ticker, days):
        asked.append(days)
        return [{"date": "2021-08-13", "close": 10.0}, {"date": "2026-01-02", "close": 50.0}]

    with patch("routers.simulator.get_price_history", side_effect=fake_history):
        g = growth_simulation(ticker="OLD", amount=100.0, db=db)
    assert g["entry_date"] == "2021-08-13" and g["points"][-1]["value"] == 500.0
    assert min(asked) > 365 * 4
    db.query(Trade).delete()
    db.query(Politician).delete()
    db.commit()
