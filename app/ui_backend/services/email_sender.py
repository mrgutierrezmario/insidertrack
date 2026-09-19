"""
Sends analysis report emails via Gmail SMTP.
Requires MAIL_USERNAME and MAIL_PASSWORD (Gmail App Password) in .env.
"""

import html
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from config import settings
from models.analysis import DailyAnalysis


def _e(value) -> str:
    """HTML-escape a value before interpolating into a template string.
    Defends against injection from any user/feed-controlled field (tickers,
    insider names, reasons) that flows from the DB into the email body.
    """
    return html.escape("" if value is None else str(value), quote=True)

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
    """Build the message with the shared headers (From, optional Reply-To)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _safe_from(from_addr)
    msg["To"] = recipient
    reply_to = (settings.mail_reply_to or "").replace("\r", "").replace("\n", "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(html_body, "html"))
    return msg

SIGNAL_COLOR = {"BUY": "#4ade80", "SELL": "#f87171", "HOLD": "#fbbf24"}
SIGNAL_BG = {"BUY": "#052e16", "SELL": "#450a0a", "HOLD": "#1c1917"}


def _build_html(analysis: DailyAnalysis) -> str:
    period_label = analysis.period.capitalize()
    signals = analysis.signals or []
    bullish = analysis.tickers_bullish or []
    bearish = analysis.tickers_bearish or []

    signal_rows = ""
    for s in signals:
        signal_value = s.get("signal", "HOLD")
        color = SIGNAL_COLOR.get(signal_value, "#fbbf24")
        bg = SIGNAL_BG.get(signal_value, "#1c1917")
        price = f"${_e(s['current_price'])}" if s.get("current_price") else "—"
        insiders = _e(", ".join(s.get("insiders", []))) or "—"
        signal_rows += f"""
        <tr>
          <td style="padding:10px 12px;color:#38bdf8;font-weight:700">{_e(s['ticker'])}</td>
          <td style="padding:10px 12px">
            <span style="background:{bg};color:{color};padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700">
              {_e(signal_value)}
            </span>
          </td>
          <td style="padding:10px 12px;color:#e2e8f0">{price}</td>
          <td style="padding:10px 12px;color:#94a3b8;font-size:13px">{_e(s.get('reason',''))}</td>
          <td style="padding:10px 12px;color:#64748b;font-size:12px">{insiders}</td>
        </tr>"""

    buy_chips = "".join(
        f'<span style="background:#052e16;color:#4ade80;padding:3px 10px;border-radius:4px;margin:3px;display:inline-block">↑ {_e(t)}</span>'
        for t in bullish
    ) or '<span style="color:#4b5563">None</span>'

    sell_chips = "".join(
        f'<span style="background:#450a0a;color:#f87171;padding:3px 10px;border-radius:4px;margin:3px;display:inline-block">↓ {_e(t)}</span>'
        for t in bearish
    ) or '<span style="color:#4b5563">None</span>'

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="background:#0f1117;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:0">
  <div style="max-width:680px;margin:0 auto;padding:32px 24px">

    <div style="margin-bottom:24px">
      <span style="color:#38bdf8;font-size:20px;font-weight:700">📈 InsiderTrack</span>
      <span style="color:#64748b;font-size:14px;margin-left:12px">{_e(period_label)} Report · {_e(analysis.analysis_date)}</span>
    </div>

    <div style="display:flex;gap:16px;margin-bottom:24px">
      <div style="background:#161b27;border:1px solid #1e2533;border-radius:8px;padding:16px;flex:1">
        <div style="color:#64748b;font-size:11px;text-transform:uppercase;margin-bottom:8px">Buy signals</div>
        {buy_chips}
      </div>
      <div style="background:#161b27;border:1px solid #1e2533;border-radius:8px;padding:16px;flex:1">
        <div style="color:#64748b;font-size:11px;text-transform:uppercase;margin-bottom:8px">Sell signals</div>
        {sell_chips}
      </div>
    </div>

    {"<table style='width:100%;border-collapse:collapse;background:#161b27;border:1px solid #1e2533;border-radius:8px;overflow:hidden'><thead><tr style='border-bottom:1px solid #1e2533'><th style='padding:10px 12px;text-align:left;color:#64748b;font-size:11px;text-transform:uppercase'>Ticker</th><th style='padding:10px 12px;text-align:left;color:#64748b;font-size:11px;text-transform:uppercase'>Signal</th><th style='padding:10px 12px;text-align:left;color:#64748b;font-size:11px;text-transform:uppercase'>Price</th><th style='padding:10px 12px;text-align:left;color:#64748b;font-size:11px;text-transform:uppercase'>Reason</th><th style='padding:10px 12px;text-align:left;color:#64748b;font-size:11px;text-transform:uppercase'>Insiders</th></tr></thead><tbody>" + signal_rows + "</tbody></table>" if signals else "<p style='color:#4b5563;text-align:center;padding:32px'>No signals yet — sync trades from the dashboard first.</p>"}

    <div style="margin-top:32px;padding-top:16px;border-top:1px solid #1e2533;color:#4b5563;font-size:12px;text-align:center">
      InsiderTrack · Based on public STOCK Act disclosures · Not financial advice
    </div>
  </div>
</body>
</html>"""


def send_report(analysis: DailyAnalysis, recipients: list[str]) -> bool:
    if not recipients:
        return True
    if not settings.mail_username or not settings.mail_password:
        logger.warning("Email not configured — skipping report send. Add MAIL_PASSWORD to .env.")
        return False

    subject = f"InsiderTrack {analysis.period.capitalize()} Report — {analysis.analysis_date}"
    html = _build_html(analysis)
    from_addr = settings.mail_from or settings.mail_username

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.mail_username, settings.mail_password)
            for recipient in recipients:
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
    return send_simple_email(subject, html_body, [to])


def send_simple_email(subject: str, html_body: str, recipients: list[str]) -> bool:
    """Send a plain HTML email — used for alert notifications."""
    if not recipients:
        return True
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
