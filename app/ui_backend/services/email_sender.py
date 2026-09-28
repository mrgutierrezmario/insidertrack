"""
Sends analysis report emails via Gmail SMTP.
Requires MAIL_USERNAME and MAIL_PASSWORD (Gmail App Password) in .env.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from config import settings
from models.analysis import DailyAnalysis
from services.email_layout import (
    DOWN_BG,
    DOWN_FG,
    HOLD_BG,
    HOLD_FG,
    LINE,
    MUTED,
    PAGE,
    SITE_URL,
    TEXT,
    UP_BG,
    UP_FG,
    button,
    e,
    layout,
    pill,
    to_text,
)

# Kept for callers that import it; same escaping as email_layout.e.
_e = e

logger = logging.getLogger(__name__)


def _safe_from(addr: str) -> str:
    """Build a `From:` header safe against CR/LF injection.

    `mail_from_name` is admin-settable, so a value containing `\\r\\n` would
    let an attacker prepend arbitrary headers (Bcc, etc.). `formataddr`
    quotes the display name, and we strip control chars defensively.
    """
    name = (settings.mail_from_name or "InsiderTrack").replace("\r", "").replace("\n", "").strip()
    addr = (addr or "").replace("\r", "").replace("\n", "").strip()
    return formataddr((name, addr))


def _new_message(subject: str, from_addr: str, recipient: str, html_body: str) -> MIMEMultipart:
    """Build the message with the shared headers (From, optional Reply-To).

    Plain text first, HTML second (clients show the last part they can
    render); the text part also helps deliverability."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _safe_from(from_addr)
    msg["To"] = recipient
    reply_to = (settings.mail_reply_to or "").replace("\r", "").replace("\n", "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(to_text(html_body), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


SIGNAL_STYLE = {"BUY": (UP_FG, UP_BG), "SELL": (DOWN_FG, DOWN_BG), "HOLD": (HOLD_FG, HOLD_BG)}


def _build_html(analysis: DailyAnalysis, manage_url: str = "") -> str:
    period_label = analysis.period.capitalize()
    signals = analysis.signals or []
    bullish = analysis.tickers_bullish or []
    bearish = analysis.tickers_bearish or []

    th = f"padding:8px 10px;text-align:left;color:{MUTED};font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid {LINE};"
    td = f"padding:10px;border-bottom:1px solid {LINE};vertical-align:top;"
    rows = ""
    for s in signals:
        value = s.get("signal", "HOLD")
        fg, bg = SIGNAL_STYLE.get(value, SIGNAL_STYLE["HOLD"])
        price = f"${e(s['current_price'])}" if s.get("current_price") else "–"
        insiders = e(", ".join(s.get("insiders", []))) or "–"
        rows += (
            f"<tr>"
            f'<td style="{td}color:{TEXT};font-weight:800;">{e(s["ticker"])}</td>'
            f'<td style="{td}">{pill(value, fg, bg)}</td>'
            f'<td style="{td}color:{TEXT};">{price}</td>'
            f'<td style="{td}color:{TEXT};font-size:13px;">{e(s.get("reason", ""))}</td>'
            f'<td style="{td}color:{MUTED};font-size:12px;">{insiders}</td>'
            f"</tr>"
        )

    buys = "".join(pill(f"↑ {t}", UP_FG, UP_BG) for t in bullish) or f'<span style="color:{MUTED};">None</span>'
    sells = "".join(pill(f"↓ {t}", DOWN_FG, DOWN_BG) for t in bearish) or f'<span style="color:{MUTED};">None</span>'
    box = f"background:{PAGE};border:1px solid {LINE};border-radius:8px;padding:14px 16px;vertical-align:top;"
    label = f"margin:0 0 8px;color:{MUTED};font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;"

    body = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="48%" style="{box}"><p style="{label}">Buy signals</p>{buys}</td>'
        f'<td width="4%" style="font-size:0;line-height:0;">&nbsp;</td>'
        f'<td width="48%" style="{box}"><p style="{label}">Sell signals</p>{sells}</td>'
        f"</tr></table>"
    )
    if signals:
        body += (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:20px;border-collapse:collapse;">'
            f'<tr><th style="{th}">Ticker</th><th style="{th}">Signal</th><th style="{th}">Price</th>'
            f'<th style="{th}">Reason</th><th style="{th}">Insiders</th></tr>{rows}</table>'
        )
    else:
        body += f'<p style="color:{MUTED};margin:20px 0 0;">No signals yet. Sync trades from the dashboard first.</p>'
    body += button("Open InsiderTrack", SITE_URL)
    if manage_url:
        body += (
            f'<p style="margin:16px 0 0;color:{MUTED};font-size:13px;">'
            f'<a href="{e(manage_url)}" style="color:{MUTED};">Change or cancel these emails</a></p>'
        )

    return layout(
        f"{period_label} report · {analysis.analysis_date}",
        body,
        eyebrow="InsiderTrack report",
        preheader=f"{len(bullish)} bullish, {len(bearish)} bearish",
        footer_note="Based on public STOCK Act and SEC disclosures. Not financial advice.",
    )


def send_report(analysis: DailyAnalysis, recipients: list[str], manage_urls: dict[str, str] | None = None) -> bool:
    """``manage_urls`` maps a recipient to their own signed manage link."""
    if not recipients:
        return True
    if not settings.mail_username or not settings.mail_password:
        logger.warning("Email not configured — skipping report send. Add MAIL_PASSWORD to .env.")
        return False

    subject = f"InsiderTrack {analysis.period} report · {analysis.analysis_date}"
    manage_urls = manage_urls or {}
    from_addr = settings.mail_from or settings.mail_username

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.mail_username, settings.mail_password)
            for recipient in recipients:
                html = _build_html(analysis, manage_urls.get(recipient, ""))
                msg = _new_message(subject, from_addr, recipient, html)
                server.sendmail(from_addr, [recipient], msg.as_string())
        logger.info(f"Report sent to {len(recipients)} recipient(s) for {analysis.period}")
        return True
    except Exception as e:
        logger.error(f"Failed to send report: {e}")
        return False


def send_admin_email(subject: str, html_body: str) -> bool:
    """Operational notice to the site operator (MAIL_ADMIN_TO, else the
    sending account). Logged at WARNING as well so it shows up even when
    mail isn't configured."""
    logger.warning(f"[admin notice] {subject}")
    to = settings.mail_admin_to or settings.mail_from or settings.mail_username
    if not to:
        return False
    return send_simple_email(subject, html_body, [to], eyebrow="Admin notice")


def send_simple_email(
    subject: str,
    html_body: str,
    recipients: list[str],
    *,
    title: str | None = None,
    eyebrow: str = "",
    preheader: str = "",
    footer_note: str = "",
) -> bool:
    """Send one email. ``html_body`` is a fragment; it goes out in the shared
    layout (a full document passed in is sent as is)."""
    if not recipients:
        return True
    if not html_body.lstrip().lower().startswith("<!doctype"):
        html_body = layout(
            title or subject, html_body, eyebrow=eyebrow, preheader=preheader, footer_note=footer_note
        )
    if not settings.mail_username or not settings.mail_password:
        logger.warning("Email not configured — skipping alert email.")
        return False

    from_addr = settings.mail_from or settings.mail_username

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.mail_username, settings.mail_password)
            for recipient in recipients:
                msg = _new_message(subject, from_addr, recipient, html_body)
                server.sendmail(from_addr, [recipient], msg.as_string())
        logger.info(f"Alert email sent to {len(recipients)} recipient(s)")
        return True
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")
        return False
