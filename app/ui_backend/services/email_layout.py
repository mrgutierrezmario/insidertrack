"""The one look every InsiderTrack email shares.

Same design family as mgnetsolutions.com and the other apps: a navy header
with the MG logo and the product name, the blue-teal line, a white card, and
a footer naming M.G. Network and Technology Solutions.

Built for inboxes, not browsers: table layout and inline styles (what Gmail,
Apple Mail and Outlook all render), a light card (Gmail drops page
backgrounds, which made the old dark emails unreadable), one small hosted
logo, and a plain-text part generated alongside, so the messages read as
transactional mail and stay out of Promotions.
"""

import html
import re
from html.parser import HTMLParser

SITE_URL = "https://insidertrack.mgnetsolutions.com"
LOGO_URL = "https://mgnetsolutions.com/email-logo.png"
PRODUCT = "InsiderTrack"
COMPANY = "M.G. Network and Technology Solutions"

# Light palette, from the site's tokens.
NAVY = "#0a1430"
PAGE = "#f4f6fa"
CARD = "#ffffff"
TEXT = "#0b1b36"
MUTED = "#51607a"
LINE = "#dfe5ee"
ACCENT = "#0a5fd1"
TEAL = "#12bceb"
UP_FG, UP_BG = "#15803d", "#e8f7ee"
DOWN_FG, DOWN_BG = "#b91c1c", "#fdecec"
HOLD_FG, HOLD_BG = "#92400e", "#fef3c7"

FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def e(value) -> str:
    """HTML-escape anything that came from data, a feed or a user."""
    return html.escape("" if value is None else str(value), quote=True)


def button(label: str, href: str) -> str:
    """A table-based button (renders in Outlook too)."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px 0 4px;">'
        f'<tr><td style="border-radius:8px;background:{ACCENT};">'
        f'<a href="{e(href)}" style="display:inline-block;padding:12px 22px;color:#ffffff;'
        f'font-size:15px;font-weight:700;text-decoration:none;">{e(label)}</a>'
        f"</td></tr></table>"
    )


def pill(text: str, fg: str, bg: str) -> str:
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};padding:3px 10px;'
        f'border-radius:999px;font-size:12px;font-weight:700;margin:2px 4px 2px 0;">{e(text)}</span>'
    )


def layout(title: str, body: str, *, eyebrow: str = "", preheader: str = "", footer_note: str = "") -> str:
    """Wrap an HTML fragment in the shared email shell."""
    pre = (
        f'<div style="display:none;max-height:0;overflow:hidden;">{e(preheader)}</div>' if preheader else ""
    )
    eyebrow_html = (
        f'<p style="margin:0 0 6px;color:{ACCENT};font-size:12px;font-weight:700;'
        f'letter-spacing:.08em;text-transform:uppercase;">{e(eyebrow)}</p>'
        if eyebrow
        else ""
    )
    note = f"{e(footer_note)}<br>" if footer_note else ""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{e(title)}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE};">
{pre}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE};">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:{CARD};border:1px solid {LINE};border-radius:10px;overflow:hidden;font-family:{FONT};">
      <tr><td style="background:{NAVY};padding:20px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="vertical-align:middle;"><a href="{SITE_URL}" style="text-decoration:none;"><img src="{LOGO_URL}" width="120" height="65" alt="{e(COMPANY)}" style="display:block;border:0;"></a></td>
          <td align="right" style="vertical-align:middle;color:#ffffff;font-size:20px;font-weight:800;letter-spacing:-.2px;">{e(PRODUCT)}</td>
        </tr></table>
      </td></tr>
      <tr><td style="height:4px;line-height:4px;font-size:0;background:{TEAL};background-image:linear-gradient(90deg,#0B74F6,#12BCEB 52%,#11D4B2);">&nbsp;</td></tr>
      <tr><td style="padding:28px 28px 12px;color:{TEXT};font-size:15px;line-height:1.55;">
        {eyebrow_html}
        <h1 style="margin:0 0 16px;color:{TEXT};font-size:22px;line-height:1.3;">{e(title)}</h1>
        {body}
      </td></tr>
      <tr><td style="padding:20px 28px 26px;color:{MUTED};font-size:12px;line-height:1.5;border-top:1px solid {LINE};">
        {note}{e(PRODUCT)} by {e(COMPANY)} · <a href="{SITE_URL}" style="color:{MUTED};">insidertrack.mgnetsolutions.com</a>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


class _Text(HTMLParser):
    """Turns the email HTML into a readable plain-text part."""

    BLOCK = frozenset({"p", "div", "tr", "h1", "h2", "h3", "li", "table", "ul", "ol"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "title", "head"):
            self.skip += 1
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "td":
            self.out.append("  ")
        elif tag == "a":
            self.href = dict(attrs).get("href")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "title", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a":
            if self.href and self.href.startswith("http"):
                self.out.append(f" ({self.href})")
            self.href = None
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def to_text(html_doc: str) -> str:
    """Plain-text alternative for an email built with :func:`layout`."""
    # Drop the hidden preheader, and everything up to the gradient line (the
    # logo + product-name header): text readers start at the content.
    body = re.sub(r'<div style="display:none[^>]*>.*?</div>', "", html_doc, flags=re.DOTALL)
    cut = body.find("linear-gradient(90deg")
    if cut != -1:
        body = body[body.find("</tr>", cut) + len("</tr>"):]
    parser = _Text()
    parser.feed(body)
    text = "".join(parser.out).replace("\xa0", " ")
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
