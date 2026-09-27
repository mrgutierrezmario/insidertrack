"""Every InsiderTrack email goes out in the shared layout, with a plain-text
part, and nothing from data or users reaches the HTML unescaped."""

import email
from unittest.mock import patch

from services import email_sender
from services.email_layout import layout, to_text


class _FakeSMTP:
    sent: list[str] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def sendmail(self, _from, _to, raw):
        _FakeSMTP.sent.append(raw)


def _send(monkeypatch, *args, **kwargs):
    monkeypatch.setattr(email_sender.settings, "mail_username", "sender@example.com")
    monkeypatch.setattr(email_sender.settings, "mail_password", "x")
    _FakeSMTP.sent = []
    with patch("smtplib.SMTP_SSL", _FakeSMTP):
        assert email_sender.send_simple_email(*args, **kwargs)
    return email.message_from_string(_FakeSMTP.sent[0])


def _parts(msg):
    return {
        p.get_content_type(): p.get_payload(decode=True).decode()
        for p in msg.walk()
        if p.get_content_type() in ("text/plain", "text/html")
    }


def test_fragment_is_wrapped_in_the_layout_with_a_text_part(monkeypatch):
    msg = _send(monkeypatch, "InsiderTrack: 1 new alert", "<p>NVDA matched.</p>", ["u@example.com"], title="1 new alert")
    parts = _parts(msg)
    assert set(parts) == {"text/plain", "text/html"}
    assert "https://mgnetsolutions.com/email-logo.png" in parts["text/html"]
    assert "InsiderTrack by M.G. Network and Technology Solutions" in parts["text/html"]
    assert "NVDA matched." in parts["text/plain"]
    # The text part starts at the content, not the logo/header.
    assert parts["text/plain"].lstrip().startswith("1 new alert")


def test_title_and_notes_are_escaped():
    doc = layout("<script>x</script>", "<p>ok</p>", eyebrow="<b>e</b>", footer_note="<i>n</i>")
    assert "<script>x" not in doc and "&lt;script&gt;" in doc
    assert "<b>e</b>" not in doc and "<i>n</i>" not in doc


def test_report_escapes_feed_fields():
    from types import SimpleNamespace

    analysis = SimpleNamespace(
        period="daily",
        analysis_date="2026-09-27",
        tickers_bullish=["<img src=x>"],
        tickers_bearish=[],
        signals=[{"ticker": "<b>T</b>", "signal": "BUY", "reason": "<script>r</script>", "insiders": ["<i>n</i>"]}],
    )
    doc = email_sender._build_html(analysis)
    for raw in ("<img src=x>", "<b>T</b>", "<script>r", "<i>n</i>"):
        assert raw not in doc
    assert "Not financial advice" in to_text(doc)
