from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class WatchlistItem(Base):
    """
    A ticker a visitor wants to follow. Keyed by email (the same email
    collected at the terms screen). Access is gated by the bearer token stored
    in the WatchlistOwner row for this email — see routers/watchlist.py.
    """
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("email", "ticker", name="uq_watchlist_email_ticker"),)

    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String(255), index=True, nullable=False)
    ticker     = Column(String(20), nullable=False)
    note       = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WatchlistOwner(Base):
    """
    Per-email bearer token for the watchlist. Replaces the prior "email as the
    auth key" pattern. The token itself is never stored — only its sha256 hash —
    so a DB leak can't be used to read anyone's watchlist.

    Lifecycle: minted on the first POST /watchlist/ for a new email (returned
    once in the response). Required as `Authorization: Bearer <token>` on every
    read or mutation. Lost tokens are recovered via POST /watchlist/recover,
    which emails the address a fresh token (rotates the stored hash).
    """
    __tablename__ = "watchlist_owners"

    email        = Column(String(255), primary_key=True)
    token_hash   = Column(String(64), nullable=False)  # sha256 hex
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
