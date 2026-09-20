"""
Paper (scanned, often handwritten) PTRs, read with a vision model.

About 13% of House PTRs and ~7% of Senate PTRs are filed on paper — a form
where the asset is written out by name and the amount is a ticked column or
a bracket. They have no text layer and classic OCR returns garbage on
handwriting, so we render each page (House: a PDF; Senate: GIF page images)
and ask the configured AI provider (Claude / Gemini / OpenAI, whichever the
site uses for research notes) for a structured reading. Rows land in
`trades` with source="house-paper" / "senate-paper" and the model's per-row
confidence in raw_data, so the UI can say "read by AI from a scanned form"
instead of pretending.

Cost control: PAPER_MAX_PER_RUN filings per sync; site keys only (never a
visitor's); skipped entirely when no provider is configured.
"""

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PAPER_MAX_PER_RUN = 25
PACE_SECONDS = 5          # between readings — Gemini/Claude free tiers cap requests per minute
MAX_PAGES = 6
RENDER_DPI = 150

# The form's amount columns, left to right. Column K is "spouse/dependent
# child asset over $1,000,000" — no upper bound.
AMOUNT_COLUMNS = {
    "A": "$1,001 - $15,000", "B": "$15,001 - $50,000", "C": "$50,001 - $100,000",
    "D": "$100,001 - $250,000", "E": "$250,001 - $500,000", "F": "$500,001 - $1,000,000",
    "G": "$1,000,001 - $5,000,000", "H": "$5,000,001 - $25,000,000", "I": "$25,000,001 - $50,000,000",
    "J": "Over $50,000,000", "K": "Over $1,000,000",
}

_CHAMBER_INTRO = {
    "house": "You are reading a scanned, possibly handwritten U.S. House of Representatives Periodic Transaction Report (PTR).",
    "senate": "You are reading a scanned, possibly handwritten U.S. Senate Periodic Transaction Report (PTR) — columns are #, Transaction Date, Owner, Ticker, Asset Name, Asset Type, Type (Purchase / Sale (Full) / Sale (Partial) / Exchange), Amount, Comment.",
}

PROMPT = """{intro}
Extract EVERY transaction row from the table. For each row give:
- "asset": the full asset name exactly as written (it is a company or fund name, usually not a ticker)
- "ticker": the ticker symbol if one appears anywhere in the row — in parentheses, in a ticker column, or as the trailing all-caps token of the asset name (brokerage statements print ETFs like "Ishares TR 3-7 Yr Treas Bd ETF TLH" → "TLH"); otherwise null
- "owner": "SP" (spouse), "DC" (dependent child), "JT" (joint) or "" (the filer) — from the Owner column
- "type": "P" (purchase), "S" (sale), "S (partial)" or "E" (exchange) — from the Type of Transaction column
- "transaction_date": MM/DD/YYYY from the Date of Transaction column
- "notification_date": MM/DD/YYYY from the Date Notified column, or null
- "amount": the LETTER of the ticked box in the Amount columns (A through K) if the form uses tick boxes, otherwise the dollar range exactly as written (e.g. "$1,001 - $15,000"); null if illegible
- "confidence": 0 to 1, how sure you are of this row overall
Also report "amendment": true if the "Amendment" box at the top is ticked (else false), and "filer": the name written at the top.
Amount columns: A $1,001-$15,000 · B $15,001-$50,000 · C $50,001-$100,000 · D $100,001-$250,000 · E $250,001-$500,000 · F $500,001-$1,000,000 · G $1,000,001-$5,000,000 · H $5,000,001-$25,000,000 · I $25,000,001-$50,000,000 · J over $50,000,000 · K spouse/DC over $1,000,000.
Two-digit years mean 20YY. Do not invent rows; if a row is illegible, include it with what you can read and low confidence.
Return ONLY a JSON object: {{"filer": "...", "amendment": false, "transactions": [ ... ]}}"""


def images_to_png(images: list[bytes], max_pages: int = MAX_PAGES) -> list[bytes]:
    """GIF/JPEG page scans → PNG bytes (the providers don't all take GIF)."""
    import io
    from PIL import Image
    out = []
    for raw in images[:max_pages]:
        with Image.open(io.BytesIO(raw)) as im:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="PNG")
            out.append(buf.getvalue())
    return out


def render_pdf_pages(pdf_bytes: bytes, max_pages: int = MAX_PAGES, dpi: int = RENDER_DPI) -> list[bytes]:
    """PNG bytes per page via poppler's pdftoppm (installed in the image)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(pdf_bytes)
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", "-f", "1", "-l", str(max_pages), str(src), str(Path(tmp) / "pg")],
            check=True, capture_output=True, timeout=120,
        )
        return [p.read_bytes() for p in sorted(Path(tmp).glob("pg-*.png"))]


def _parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _year4(d: Optional[str]) -> Optional[str]:
    """'4/16/26' → '04/16/2026'; passes MM/DD/YYYY through; None when unparsable."""
    if not d:
        return None
    m = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$", d)
    if not m:
        return None
    mm, dd, yy = m.groups()
    if len(yy) == 2:
        yy = "20" + yy
    return f"{int(mm):02d}/{int(dd):02d}/{yy}"


_TICKER_SHAPE = re.compile(r"[A-Z][A-Z.\-]{0,5}")


def resolve_ticker(row: dict, ticker_lookup, is_ticker=None) -> str:
    """Ticker for a read row, in order: the model's ticker field; the SEC
    name map on the asset name; a trailing all-caps token of the asset name
    ("… ETF TLH"). `is_ticker(sym)` — when given — must confirm the symbol
    exists (SEC company list) before a bare token is trusted."""
    def ok(sym: str) -> bool:
        return bool(sym and _TICKER_SHAPE.fullmatch(sym) and (is_ticker is None or is_ticker(sym)))
    cand = (row.get("ticker") or "").strip().upper().strip("()")
    if ok(cand):
        return cand
    asset = (row.get("asset") or "").strip()
    by_name = ticker_lookup(asset) if asset else ""
    if by_name:
        return by_name
    tail = asset.split()[-1].strip("()") if asset else ""
    if tail.isupper() and ok(tail):
        return tail
    return ""


def _normalize_amount(raw) -> Optional[str]:
    """A tick-box letter → its bracket; a written range → the canonical
    bracket whose lower bound matches (so "$1,001-$15,000", "1,001 - 15,000"
    and "A" all become "$1,001 - $15,000"); anything else → None."""
    from services.trade_semantics import parse_amount_range
    v = (raw or "").strip()
    if not v:
        return None
    if len(v) == 1 and v.upper() in AMOUNT_COLUMNS:
        return AMOUNT_COLUMNS[v.upper()]
    low, high = parse_amount_range(v)
    if low is None:
        return None
    for bracket in AMOUNT_COLUMNS.values():
        b_low, _ = parse_amount_range(bracket)
        if b_low == low:
            return bracket
    return f"${low:,} - ${high:,}" if high else f"Over ${low:,}"


def rows_from_reading(reading: dict, ticker_lookup, is_ticker=None) -> tuple[list[dict], dict]:
    """Turn the model's JSON into parser-shaped transaction dicts (the same
    shape `_parse_house_text` yields) so the normal insert path applies.
    `ticker_lookup(asset_name) -> ticker or ''` resolves names; `is_ticker`
    validates bare symbols. Rows with no resolvable ticker, no date, or no
    amount are dropped and counted."""
    stats = {"rows": 0, "kept": 0, "no_ticker": 0, "no_date": 0, "no_amount": 0, "low_confidence": 0}
    out = []
    for r in reading.get("transactions") or []:
        stats["rows"] += 1
        conf = float(r.get("confidence") or 0)
        ticker = resolve_ticker(r, ticker_lookup, is_ticker)
        if not ticker:
            stats["no_ticker"] += 1
            continue
        td = _year4(r.get("transaction_date"))
        if not td:
            stats["no_date"] += 1
            continue
        amount = _normalize_amount(r.get("amount"))
        if not amount:
            stats["no_amount"] += 1
            continue
        if conf < 0.4:
            stats["low_confidence"] += 1
            continue
        ty = (r.get("type") or "").strip().upper()
        tx_type = "purchase" if ty.startswith("P") else "exchange" if ty.startswith("E") else \
                  ("sale_partial" if "PART" in ty else "sale") if ty.startswith("S") else ""
        if not tx_type:
            continue
        out.append({
            "ticker": ticker, "type": tx_type, "transaction_date": td,
            "disclosure_date": _year4(r.get("notification_date")) or td,
            "amount": amount, "asset_type": "stock", "asset_name": (r.get("asset") or "").strip()[:200],
            "owner": (r.get("owner") or "").strip().upper()[:2],
            "tx_id": None, "status": "new", "amended": bool(reading.get("amendment")),
            "ai_confidence": round(conf, 2),
        })
        stats["kept"] += 1
    return out, stats


def read_paper_pages(pages: list[bytes], chamber: str = "house") -> Optional[dict]:
    """Ask the configured provider to read PNG page images. None when no
    provider is set up or the reading failed (caller retries next sync)."""
    from services.providers import ProviderError, active_provider, generate_text
    if active_provider() is None or not pages:
        return None
    prompt = PROMPT.format(intro=_CHAMBER_INTRO.get(chamber, _CHAMBER_INTRO["house"]))
    try:
        gen = generate_text(prompt, max_tokens=2500, timeout=120.0, images=pages, job="vision")
    except ProviderError as exc:
        logger.warning(f"paper PTR reading failed: {exc}")
        return None
    reading = _parse_json(gen.text)
    if reading is None:
        logger.warning("paper PTR reading: model returned no JSON")
        return None
    reading["_model"] = gen.provider
    return reading


def read_paper_ptr(pdf_bytes: bytes) -> Optional[dict]:
    """House: render the PDF, then read."""
    try:
        pages = render_pdf_pages(pdf_bytes)
    except Exception as exc:
        logger.warning(f"paper PTR render failed: {exc}")
        return None
    return read_paper_pages(pages, "house")


def read_senate_paper(gif_pages: list[bytes]) -> Optional[dict]:
    """Senate: EFD serves paper filings as GIF page scans."""
    try:
        pages = images_to_png(gif_pages)
    except Exception as exc:
        logger.warning(f"senate paper PTR image conversion failed: {exc}")
        return None
    return read_paper_pages(pages, "senate")
