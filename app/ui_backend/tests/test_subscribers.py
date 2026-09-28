"""
Email-report subscriptions: a stranger who knows (or makes up) an address
must not be able to start reports to it, read its settings, change them or
cancel them. Only the emailed link (or the admin) can.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from models.subscriber import EmailSubscriber
from routers import config as cfg
from routers import watchlist as wl_router
from routers.config import (
    ManageLinkIn,
    SubscriberCreate,
    SubscriberUpdate,
    add_subscriber,
    confirm_subscriber,
    delete_subscriber,
    lookup_subscriber,
    request_manage_link,
    update_subscriber,
)
from services.scheduler import _get_subscribers_for_period
from services.subscriber_links import sub_sig


def _request(ip: str = "203.0.113.9"):
    req = MagicMock()
    req.headers.get.side_effect = lambda k, default=None: default
    req.cookies = {}
    req.client.host = ip
    return req


@pytest.fixture(autouse=True)
def _clean(db):
    cfg._sub_hits.clear()
    cfg._mail_hits.clear()
    wl_router._get_hits.clear()
    db.query(EmailSubscriber).delete()
    db.commit()
    yield


def _subscribe(db, email="new@example.com"):
    with patch("services.email_sender.send_simple_email") as send:
        resp = add_subscriber(SubscriberCreate(email=email), _request(), x_admin_token=None, db=db)
    return resp, send


def _confirmed(db, email="me@example.com"):
    row = EmailSubscriber(email=email, confirmed=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestSignup:
    def test_new_signup_is_unconfirmed_and_gets_no_reports(self, db):
        resp, send = _subscribe(db)
        assert resp == {"status": "check_email"}
        row = db.query(EmailSubscriber).one()
        assert row.confirmed is False
        send.assert_called_once()
        assert _get_subscribers_for_period(db, "morning") == []

    def test_confirm_link_turns_reports_on(self, db):
        _subscribe(db)
        row = db.query(EmailSubscriber).one()
        redirect = confirm_subscriber(sub=row.id, sig=sub_sig(row), db=db)
        assert redirect.status_code == 302
        db.refresh(row)
        assert row.confirmed is True
        assert [s.email for s in _get_subscribers_for_period(db, "morning")] == ["new@example.com"]

    def test_forged_confirm_link_does_nothing(self, db):
        _subscribe(db)
        row = db.query(EmailSubscriber).one()
        confirm_subscriber(sub=row.id, sig="0" * 32, db=db)
        db.refresh(row)
        assert row.confirmed is False

    def test_existing_subscriber_gets_same_answer(self, db):
        _confirmed(db, "me@example.com")
        resp, send = _subscribe(db, "me@example.com")
        # Same reply as a new address, so the form can't reveal who subscribes.
        assert resp == {"status": "check_email"}
        # They get the manage link, not a second subscription.
        send.assert_called_once()
        assert db.query(EmailSubscriber).count() == 1

    def test_one_address_cant_be_mail_bombed(self, db):
        sends = 0
        for i in range(6):
            cfg._sub_hits.clear()  # a different IP each time
            _, send = _subscribe(db, "victim@example.com")
            sends += send.call_count
        assert sends == cfg._MAIL_MAX

    def test_ip_rate_limit(self, db):
        for _ in range(cfg._SUB_MAX):
            _subscribe(db, "a@example.com")
        with pytest.raises(HTTPException) as exc:
            _subscribe(db, "a@example.com")
        assert exc.value.status_code == 429


class TestManage:
    def test_lookup_needs_the_signed_link(self, db):
        row = _confirmed(db)
        with pytest.raises(HTTPException) as exc:
            lookup_subscriber(_request(), sub=row.id, sig="wrong", db=db)
        assert exc.value.status_code == 404
        assert lookup_subscriber(_request(), sub=row.id, sig=sub_sig(row), db=db).email == "me@example.com"

    def test_email_alone_cannot_change_or_cancel(self, db):
        row = _confirmed(db)
        with pytest.raises(HTTPException) as exc:
            update_subscriber(row.id, SubscriberUpdate(is_active=False), _request(), sig="", x_admin_token=None, db=db)
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            delete_subscriber(row.id, _request(), sig="", x_admin_token=None, db=db)
        assert exc.value.status_code == 403
        # A valid link for one row can't be used on another.
        other = _confirmed(db, "other@example.com")
        with pytest.raises(HTTPException):
            delete_subscriber(other.id, _request(), sig=sub_sig(row), x_admin_token=None, db=db)
        assert db.query(EmailSubscriber).count() == 2

    def test_signed_link_can_change_and_cancel(self, db):
        row = _confirmed(db)
        sig = sub_sig(row)
        updated = update_subscriber(row.id, SubscriberUpdate(subscribe_midday=False), _request(), sig=sig, x_admin_token=None, db=db)
        assert updated.subscribe_midday is False
        delete_subscriber(row.id, _request(), sig=sig, x_admin_token=None, db=db)
        assert db.query(EmailSubscriber).count() == 0

    def test_manage_link_only_sent_to_confirmed(self, db):
        _confirmed(db, "me@example.com")
        with patch("services.email_sender.send_simple_email") as send:
            assert request_manage_link(ManageLinkIn(email="me@example.com"), _request(), db) == {"status": "check_email"}
            assert request_manage_link(ManageLinkIn(email="ghost@example.com"), _request(), db) == {"status": "check_email"}
        assert send.call_count == 1
        assert send.call_args.args[2] == ["me@example.com"]
