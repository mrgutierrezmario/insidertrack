"""
Shared pytest fixtures.

Tests that need a database use an in-memory SQLite instance so they run
without a live PostgreSQL server. The engine is swapped in before any model
import resolves, then Base.metadata.create_all populates the tables.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from database import Base
    import models.trade, models.politician, models.whale, models.signal_outcome, models.watchlist, models.app_setting, models.processed_filing  # noqa: F401
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
