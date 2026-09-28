"""Signed links for email-report subscribers.

A subscriber proves they own the address by the link we emailed to it, not by
typing the address (anyone can type anyone's email). The signature is an HMAC
of the row id and email, so it can't be forged or moved to another row.
"""
import hashlib
import hmac

from config import settings
from services.email_layout import SITE_URL


def sub_sig(sub) -> str:
    key = f"subscriber-link:{settings.admin_password}".encode()
    return hmac.new(key, f"{sub.id}:{sub.email}".encode(), hashlib.sha256).hexdigest()[:32]


def sig_ok(sub, sig: str) -> bool:
    return bool(sig) and hmac.compare_digest(sig, sub_sig(sub))


def manage_url(sub) -> str:
    return f"{SITE_URL}/config?sub={sub.id}&sig={sub_sig(sub)}"
