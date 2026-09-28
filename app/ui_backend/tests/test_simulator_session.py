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
