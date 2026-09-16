"""
Tests for the watchlist bearer-token auth flow.

Covers the security property the AUDIT_GAPS.md item targets: an attacker who
knows the victim's email but not the token cannot read or modify the victim's
watchlist via GET / DELETE.
"""

import pytest
from unittest.mock import MagicMock, patch

from routers import watchlist as wl_router
from routers.watchlist import (
    _hash_token,
    _mint_token,
    _require_owner,
    add_to_watchlist,
    get_watchlist,
    remove_from_watchlist,
    recover_watchlist_token,
    WatchIn,
    RecoverIn,
)
from models.watchlist import WatchlistItem, WatchlistOwner
from fastapi import HTTPException


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _request(*, bearer: str | None = None, x_token: str | None = None, ip: str = "127.0.0.1"):
    """Build a minimal Request stand-in covering only what the router reads."""
    headers: dict[str, str] = {}
    if bearer is not None:
        headers["authorization"] = f"Bearer {bearer}"
    if x_token is not None:
        headers["x-watchlist-token"] = x_token
    req = MagicMock()
    req.headers.get.side_effect = lambda k, default="": headers.get(k.lower(), default)
    req.client.host = ip
    # Disable the IP-based rate limiter for these tests (separate concern).
    return req


@pytest.fixture(autouse=True)
def _reset_rate_buckets():
    """Each test starts with empty rate-limit buckets."""
    wl_router._get_hits.clear()
    wl_router._recover_hits.clear()
    yield


@pytest.fixture(autouse=True)
def _clean_watchlist_tables(db):
    """Engine is session-scoped and tests commit, so rows would leak between tests."""
    db.query(WatchlistItem).delete()
    db.query(WatchlistOwner).delete()
    db.commit()
    yield


# ── Token helpers ─────────────────────────────────────────────────────────────

class TestTokenHelpers:
    def test_mint_token_has_entropy(self):
        a, b = _mint_token(), _mint_token()
        assert a != b
        assert len(a) >= 30  # token_urlsafe(32) → ~43 chars

    def test_hash_token_stable(self):
        assert _hash_token("abc") == _hash_token("abc")
        assert len(_hash_token("abc")) == 64  # sha256 hex

    def test_hash_token_differs_per_input(self):
        assert _hash_token("abc") != _hash_token("abd")


# ── _require_owner ────────────────────────────────────────────────────────────

class TestRequireOwner:
    def test_missing_email(self, db):
        with pytest.raises(HTTPException) as exc:
            _require_owner(_request(bearer="x"), "", db)
        assert exc.value.status_code == 400

    def test_missing_token(self, db):
        db.add(WatchlistOwner(email="a@b.com", token_hash=_hash_token("real")))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _require_owner(_request(), "a@b.com", db)
        assert exc.value.status_code == 401

    def test_no_owner_row(self, db):
        with pytest.raises(HTTPException) as exc:
            _require_owner(_request(bearer="anything"), "nobody@b.com", db)
        assert exc.value.status_code == 401

    def test_seeded_empty_hash_rejects(self, db):
        """Migration seeds existing users with token_hash='' — they must recover."""
        db.add(WatchlistOwner(email="legacy@b.com", token_hash=""))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _require_owner(_request(bearer="anything"), "legacy@b.com", db)
        assert exc.value.status_code == 401

    def test_wrong_token_returns_403(self, db):
        db.add(WatchlistOwner(email="a@b.com", token_hash=_hash_token("real-token")))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _require_owner(_request(bearer="wrong-token"), "a@b.com", db)
        assert exc.value.status_code == 403

    def test_correct_token_returns_owner(self, db):
        db.add(WatchlistOwner(email="a@b.com", token_hash=_hash_token("real-token")))
        db.commit()
        owner = _require_owner(_request(bearer="real-token"), "a@b.com", db)
        assert owner.email == "a@b.com"
        assert owner.last_used_at is not None  # bumped on success

    def test_x_watchlist_token_header_works(self, db):
        db.add(WatchlistOwner(email="a@b.com", token_hash=_hash_token("real-token")))
        db.commit()
        owner = _require_owner(_request(x_token="real-token"), "a@b.com", db)
        assert owner.email == "a@b.com"

    def test_email_is_normalized(self, db):
        db.add(WatchlistOwner(email="a@b.com", token_hash=_hash_token("real-token")))
        db.commit()
        owner = _require_owner(_request(bearer="real-token"), "  A@B.com ", db)
        assert owner.email == "a@b.com"


# ── add_to_watchlist ──────────────────────────────────────────────────────────

class TestAddToWatchlist:
    def test_first_add_mints_token(self, db):
        body = WatchIn(email="new@user.com", ticker="aapl")
        resp = add_to_watchlist(body, _request(), db)
        assert resp["status"] == "added"
        assert resp["ticker"] == "AAPL"
        assert "token" in resp and len(resp["token"]) >= 30
        # Hash matches what we'd compute
        owner = db.query(WatchlistOwner).filter(WatchlistOwner.email == "new@user.com").one()
        assert owner.token_hash == _hash_token(resp["token"])

    def test_second_add_without_token_rejected(self, db):
        first = add_to_watchlist(WatchIn(email="u@e.com", ticker="AAPL"), _request(), db)
        assert "token" in first
        with pytest.raises(HTTPException) as exc:
            add_to_watchlist(WatchIn(email="u@e.com", ticker="MSFT"), _request(), db)
        assert exc.value.status_code == 401

    def test_second_add_with_correct_token_no_token_returned(self, db):
        first = add_to_watchlist(WatchIn(email="u@e.com", ticker="AAPL"), _request(), db)
        token = first["token"]
        second = add_to_watchlist(WatchIn(email="u@e.com", ticker="MSFT"), _request(bearer=token), db)
        assert second["status"] == "added"
        assert "token" not in second  # token is minted once, not echoed

    def test_second_add_with_wrong_token_rejected(self, db):
        add_to_watchlist(WatchIn(email="u@e.com", ticker="AAPL"), _request(), db)
        with pytest.raises(HTTPException) as exc:
            add_to_watchlist(WatchIn(email="u@e.com", ticker="MSFT"), _request(bearer="bogus"), db)
        assert exc.value.status_code == 403

    def test_legacy_user_first_add_mints_token(self, db):
        """Migration-seeded owner row with empty hash → POST mints a fresh token."""
        db.add(WatchlistOwner(email="old@user.com", token_hash=""))
        db.add(WatchlistItem(email="old@user.com", ticker="AAPL"))
        db.commit()
        resp = add_to_watchlist(WatchIn(email="old@user.com", ticker="MSFT"), _request(), db)
        assert "token" in resp
        owner = db.query(WatchlistOwner).filter(WatchlistOwner.email == "old@user.com").one()
        assert owner.token_hash == _hash_token(resp["token"])


# ── get_watchlist ─────────────────────────────────────────────────────────────

class TestGetWatchlist:
    def test_without_token_is_unauthorized(self, db):
        db.add(WatchlistOwner(email="u@e.com", token_hash=_hash_token("t")))
        db.add(WatchlistItem(email="u@e.com", ticker="AAPL"))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            get_watchlist(_request(), email="u@e.com", db=db)
        assert exc.value.status_code == 401

    def test_wrong_token_is_forbidden(self, db):
        db.add(WatchlistOwner(email="u@e.com", token_hash=_hash_token("real")))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            get_watchlist(_request(bearer="wrong"), email="u@e.com", db=db)
        assert exc.value.status_code == 403

    def test_correct_token_returns_items(self, db):
        db.add(WatchlistOwner(email="u@e.com", token_hash=_hash_token("real")))
        db.add(WatchlistItem(email="u@e.com", ticker="AAPL"))
        db.add(WatchlistItem(email="u@e.com", ticker="MSFT"))
        db.commit()
        items = get_watchlist(_request(bearer="real"), email="u@e.com", db=db)
        tickers = {it["ticker"] for it in items}
        assert tickers == {"AAPL", "MSFT"}


# ── remove_from_watchlist ─────────────────────────────────────────────────────

class TestRemove:
    def test_cannot_remove_other_users_item(self, db):
        """The original bug: anyone could DELETE by guessing the integer id."""
        db.add(WatchlistOwner(email="victim@e.com", token_hash=_hash_token("victim-tok")))
        db.add(WatchlistOwner(email="attacker@e.com", token_hash=_hash_token("attacker-tok")))
        item = WatchlistItem(email="victim@e.com", ticker="AAPL")
        db.add(item)
        db.commit()
        db.refresh(item)
        with pytest.raises(HTTPException) as exc:
            remove_from_watchlist(item.id, _request(bearer="attacker-tok"), email="", db=db)
        # Attacker's token won't validate against the victim's email.
        assert exc.value.status_code in (401, 403)
        # Item is still there
        assert db.query(WatchlistItem).filter(WatchlistItem.id == item.id).first() is not None

    def test_owner_can_remove(self, db):
        db.add(WatchlistOwner(email="u@e.com", token_hash=_hash_token("t")))
        item = WatchlistItem(email="u@e.com", ticker="AAPL")
        db.add(item)
        db.commit()
        db.refresh(item)
        remove_from_watchlist(item.id, _request(bearer="t"), email="", db=db)
        assert db.query(WatchlistItem).filter(WatchlistItem.id == item.id).first() is None


# ── recover ───────────────────────────────────────────────────────────────────

class TestRecover:
    def test_unknown_email_returns_ok_no_enumeration(self, db):
        with patch("services.email_sender.send_simple_email") as send:
            resp = recover_watchlist_token(RecoverIn(email="ghost@nowhere.com"), _request(), db)
        assert resp == {"status": "ok"}
        send.assert_not_called()
        # No owner row created for ghosts
        assert db.query(WatchlistOwner).filter(WatchlistOwner.email == "ghost@nowhere.com").first() is None

    def test_known_email_rotates_token_and_sends_email(self, db):
        old_hash = _hash_token("old-token")
        db.add(WatchlistOwner(email="u@e.com", token_hash=old_hash))
        db.commit()
        with patch("services.email_sender.send_simple_email") as send:
            send.return_value = True
            resp = recover_watchlist_token(RecoverIn(email="u@e.com"), _request(), db)
        assert resp == {"status": "ok"}
        # Hash changed
        owner = db.query(WatchlistOwner).filter(WatchlistOwner.email == "u@e.com").one()
        assert owner.token_hash != old_hash
        # Email was sent with the new token in body
        assert send.called
        _, args, kwargs = send.mock_calls[0]
        subject, html_body, recipients = args
        assert "u@e.com" in recipients
        # The body should contain the new token (which we can verify by hashing the
        # extracted token and checking it matches the stored hash)
        import re
        m = re.search(r"<code>([^<]+)</code>", html_body)
        assert m, f"Token not found in body: {html_body!r}"
        assert _hash_token(m.group(1)) == owner.token_hash

    def test_old_token_invalid_after_recovery(self, db):
        db.add(WatchlistOwner(email="u@e.com", token_hash=_hash_token("old")))
        db.commit()
        with patch("services.email_sender.send_simple_email"):
            recover_watchlist_token(RecoverIn(email="u@e.com"), _request(), db)
        # Old token must no longer work
        with pytest.raises(HTTPException) as exc:
            _require_owner(_request(bearer="old"), "u@e.com", db)
        assert exc.value.status_code == 403
