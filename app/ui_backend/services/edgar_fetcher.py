"""
Fetches 13F institutional holdings filings from SEC EDGAR.
Parses the InfoTable XML to extract actual stock positions.

Rate-limit: SEC asks for ≤10 req/sec, User-Agent required.
"""

import logging
import re
import time
from datetime import date, datetime
from typing import Optional
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy.orm import Session

from models.whale import WhaleHolder, WhalePosition

logger = logging.getLogger(__name__)

EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "InsiderTrack contact@insidertrack.local"}
REQUEST_DELAY = 0.12   # ~8/sec — under SEC 10/sec limit
MAX_POSITIONS = 300    # cap per holder per quarter

KNOWN_WHALES = [
    {"name": "Berkshire Hathaway (Buffett)", "cik": "0001067983", "type": "fund"},
    {"name": "Soros Fund Management",        "cik": "0001029160", "type": "fund"},
    {"name": "Renaissance Technologies",     "cik": "0001037389", "type": "fund"},
    {"name": "Bridgewater Associates",       "cik": "0001350694", "type": "fund"},
    {"name": "Bill Ackman / Pershing Square","cik": "0001336528", "type": "fund"},
    # Added 2026-09-19 (CIKs verified against EDGAR submissions). Discretionary
    # managers only — quant / multi-strat shops (Citadel, Millennium, D.E. Shaw,
    # Two Sigma, Point72) hold thousands of hedged positions that say nothing
    # about conviction.
    {"name": "Tiger Global Management",      "cik": "0001167483", "type": "fund"},
    {"name": "Duquesne Family Office (Druckenmiller)", "cik": "0001536411", "type": "fund"},
    {"name": "Appaloosa (Tepper)",           "cik": "0001656456", "type": "fund"},
    {"name": "Baupost Group (Klarman)",      "cik": "0001061768", "type": "fund"},
    {"name": "Third Point (Loeb)",           "cik": "0001040273", "type": "fund"},
    {"name": "Elliott Investment Management","cik": "0001791786", "type": "fund"},
    {"name": "Coatue Management",            "cik": "0001135730", "type": "fund"},
    {"name": "Lone Pine Capital",            "cik": "0001061165", "type": "fund"},
    {"name": "Viking Global Investors",      "cik": "0001103804", "type": "fund"},
    {"name": "Greenlight Capital (Einhorn)", "cik": "0001079114", "type": "fund"},
    {"name": "Trian Fund Management (Peltz)","cik": "0001345471", "type": "fund"},
    {"name": "Starboard Value",              "cik": "0001517137", "type": "fund"},
    {"name": "Altimeter Capital",            "cik": "0001541617", "type": "fund"},
    {"name": "Carl Icahn",                   "cik": "0000921669", "type": "individual"},
]

# Small override table for names that don't normalize cleanly
_NAME_OVERRIDES: dict[str, str] = {
    "ALPHABET": "GOOGL",
    "BERKSHIRE HATHAWAY": "BRK-B",
    "META PLATFORMS": "META",
    "AMAZON COM": "AMZN",
}

_TICKER_MAP_CACHE: dict[str, str] | None = None


# ── Company name ↔ ticker mapping ─────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    name = name.upper()
    for suffix in [
        "INCORPORATED", "CORPORATION", "COMPANY", "LIMITED",
        "INC", "CORP", "CO", "LTD", "LLC", "LP", "PLC",
        "SA", "NV", "AG", "SE", "SPA",
    ]:
        name = re.sub(rf"\b{re.escape(suffix)}\b\.?", "", name)
    # Strip share class designations
    name = re.sub(r"\b(CL|CLASS|SER|SERIES|NEW|ORD|ADR|ADS)\b\s*[A-Z0-9]?", "", name)
    name = re.sub(r"[^A-Z0-9\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _load_ticker_map() -> dict[str, str]:
    global _TICKER_MAP_CACHE
    if _TICKER_MAP_CACHE is not None:
        return _TICKER_MAP_CACHE
    try:
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            r = client.get(COMPANY_TICKERS_URL)
            r.raise_for_status()
            data = r.json()
        mapping: dict[str, str] = {}
        for entry in data.values():
            ticker = (entry.get("ticker") or "").upper().strip()
            title = entry.get("title") or ""
            if ticker and title:
                key = _normalize_name(title)
                if key:
                    mapping[key] = ticker
        # Apply known overrides
        for name_key, ticker in _NAME_OVERRIDES.items():
            mapping[name_key] = ticker
        _TICKER_MAP_CACHE = mapping
        logger.info(f"Loaded {len(mapping)} company → ticker entries from SEC")
        return mapping
    except Exception as e:
        logger.warning(f"Could not load company tickers: {e}")
        _TICKER_MAP_CACHE = {}
        return {}


def _lookup_ticker(company_name: str, ticker_map: dict[str, str]) -> str:
    key = _normalize_name(company_name)
    # Try exact normalized match
    if key in ticker_map:
        return ticker_map[key]
    # Try overrides directly
    if key in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[key]
    return ""


# ── EDGAR submissions + filing discovery ─────────────────────────────────────

def _fetch_submissions(cik_padded: str) -> Optional[dict]:
    url = f"{EDGAR_SUBMISSIONS}/CIK{cik_padded}.json"
    try:
        with httpx.Client(timeout=20, headers=HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning(f"Submissions fetch failed for CIK {cik_padded}: {e}")
        return None


def _latest_13f(submissions: dict) -> Optional[tuple[str, str, str]]:
    """
    Returns (acc_no_dashes, period_date_str, cik_raw) for the most recent 13F-HR.
    cik_raw is the unpadded CIK used in archives URLs.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    periods = recent.get("reportDate", [])
    cik_raw = str(submissions.get("cik", ""))

    for i, form in enumerate(forms):
        if form not in ("13F-HR", "13F-HR/A"):
            continue
        acc = accessions[i] if i < len(accessions) else ""
        period = periods[i] if i < len(periods) else ""
        if acc:
            return acc.replace("-", ""), period, cik_raw
    return None


# ── InfoTable XML retrieval ───────────────────────────────────────────────────

def _find_infotable_url(cik_raw: str, acc_no_dashes: str) -> Optional[str]:
    """Try common filenames then fall back to directory listing."""
    base = f"{EDGAR_ARCHIVES}/{cik_raw}/{acc_no_dashes}"
    common = [
        "form13fInfoTable.xml",
        "13fInfoTable.xml",
        "infotable.xml",
        "13F_form.xml",
        "xslForm13F_X01.xml",
    ]

    with httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True) as client:
        for fname in common:
            try:
                time.sleep(REQUEST_DELAY)
                r = client.get(f"{base}/{fname}")
                if r.status_code == 200:
                    text_lower = r.text.lower()
                    if "informationtable" in text_lower or "infotable" in text_lower:
                        return f"{base}/{fname}"
            except Exception:
                pass

        # Parse directory listing
        try:
            time.sleep(REQUEST_DELAY)
            r = client.get(f"{base}/")
            if r.status_code == 200:
                xml_names = re.findall(r'href="([^"]+\.xml)"', r.text, re.IGNORECASE)
                for name in xml_names:
                    lower = name.lower()
                    if any(kw in lower for kw in ["infotable", "13f", "information"]):
                        fname = name.split("/")[-1]
                        return f"{base}/{fname}"
                if xml_names:
                    fname = xml_names[0].split("/")[-1]
                    return f"{base}/{fname}"
        except Exception as e:
            logger.warning(f"Directory listing failed for {base}: {e}")

    return None


def _fetch_xml(url: str) -> Optional[str]:
    try:
        with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.text
    except Exception as e:
        logger.warning(f"XML fetch failed {url}: {e}")
        return None


# ── XML parsing ───────────────────────────────────────────────────────────────
# ── XML parsing ───────────────────────────────────────────────────────────────

def _strip_ns(xml_text: str) -> str:
    """Remove namespace declarations, prefixed attributes, and tag prefixes."""
    # Remove namespace declarations (xmlns="..." and xmlns:foo="...")
    xml_text = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", xml_text)
    xml_text = re.sub(r"\s+xmlns(?:\w+)?='[^']*'", "", xml_text)
    # Remove namespace-prefixed attributes (e.g., xsi:schemaLocation="...")
    # which cause ExpatError when the prefix is no longer declared
    xml_text = re.sub(r'\s+\w+:\w+="[^"]*"', " ", xml_text)
    xml_text = re.sub(r"\s+\w+:\w+='[^']*'", " ", xml_text)
    # Remove namespace prefixes from element tags (<n1:foo> → <foo>)
    xml_text = re.sub(r"<(/?)\w+:", r"<\1", xml_text)
    return xml_text


def _detect_value_scale(tables: list) -> int:
    """
    Detect whether the 'value' field is in whole dollars or thousands of dollars.
    The SEC 13F spec says thousands, but modern filers widely use whole dollars.
    Heuristic: if median(value/shares) > 1.5, values are in dollars (scale=1).
    """
    import statistics
    ratios = []
    for tbl in tables[:50]:
        v_el = tbl.find("value")
        shr_el = tbl.find("shrsOrPrnAmt")
        if v_el is None or shr_el is None:
            continue
        amt_el = shr_el.find("sshPrnamt")
        type_el = shr_el.find("sshPrnamtType")
        if amt_el is None:
            continue
        shr_type = (type_el.text or "SH").upper().strip() if type_el is not None else "SH"
        if shr_type != "SH":
            continue
        try:
            val = float((v_el.text or "0").strip())
            shares = float((amt_el.text or "0").strip())
            if shares > 100 and val > 0:
                ratios.append(val / shares)
        except (ValueError, ZeroDivisionError):
            pass

    if not ratios:
        return 1  # default to dollars when undecidable
    med = statistics.median(ratios)
    return 1 if med > 1.5 else 1000


def _parse_infotable(xml_text: str) -> list[dict]:
    """
    Parse 13F InfoTable XML → list of {company_name, cusip, value_usd, shares}.
    Auto-detects whether values are in dollars or thousands (varies by filer).
    """
    cleaned = _strip_ns(xml_text)
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as e:
        logger.warning(f"XML ParseError: {e}")
        return []

    tables = root.findall(".//infoTable")
    if not tables:
        tables = [el for el in root.iter() if el.tag.lower().endswith("infotable")]

    scale = _detect_value_scale(tables)

    holdings = []
    for tbl in tables:
        def _txt(tag: str) -> str:
            el = tbl.find(tag)
            return (el.text or "").strip() if el is not None else ""

        name = _txt("nameOfIssuer")
        cusip = _txt("cusip")
        value_str = _txt("value")

        shr_el = tbl.find("shrsOrPrnAmt")
        shares = 0
        if shr_el is not None:
            amt_el = shr_el.find("sshPrnamt")
            type_el = shr_el.find("sshPrnamtType")
            shr_type = (type_el.text or "").upper().strip() if type_el is not None else "SH"
            if amt_el is not None and shr_type == "SH":
                try:
                    shares = int(float((amt_el.text or "0").strip()))
                except ValueError:
                    pass

        if not name or not value_str:
            continue
        try:
            value_usd = int(float(value_str)) * scale
        except ValueError:
            continue
        if value_usd <= 0:
            continue

        holdings.append({"company_name": name, "cusip": cusip, "value_usd": value_usd, "shares": shares})

    holdings.sort(key=lambda h: h["value_usd"], reverse=True)
    return holdings


# ── Quarter helpers ───────────────────────────────────────────────────────────

def _quarter(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    except Exception:
        return ""


def _change_type(holder_id: int, ticker: str, current_value: int, db: Session) -> str:
    prev = (
        db.query(WhalePosition)
        .filter(WhalePosition.holder_id == holder_id, WhalePosition.ticker == ticker)
        .order_by(WhalePosition.filing_date.desc())
        .first()
    )
    if not prev:
        return "new"
    pct = (current_value - (prev.value_usd or 0)) / max(prev.value_usd or 1, 1)
    if pct > 0.05:
        return "increased"
    if pct < -0.05:
        return "decreased"
    return "stable"


# ── Public API ────────────────────────────────────────────────────────────────

def seed_whale_holders(db: Session) -> None:
    for whale in KNOWN_WHALES:
        exists = db.query(WhaleHolder).filter(WhaleHolder.cik == whale["cik"]).first()
        if not exists:
            db.add(WhaleHolder(
                name=whale["name"],
                cik=whale["cik"],
                holder_type=whale["type"],
                is_tracked=True,
            ))
    db.commit()
    logger.info("Seeded whale holders")


def fetch_latest_13f(cik: str) -> Optional[dict]:
    """Backward-compat: return raw submissions JSON for a CIK."""
    cik_padded = cik.lstrip("0").zfill(10)
    return _fetch_submissions(cik_padded)


def sync_whale_positions(db: Session) -> dict:
    """
    For each tracked whale holder, fetch the latest 13F-HR from EDGAR,
    parse the InfoTable XML, and store positions. Skips quarters already synced.
    Returns {synced: N, skipped: N, unmapped: N}.
    """
    seed_whale_holders(db)

    ticker_map = _load_ticker_map()
    time.sleep(REQUEST_DELAY)

    total_synced = 0
    total_skipped = 0
    total_unmapped = 0

    holders = db.query(WhaleHolder).filter(WhaleHolder.is_tracked == True).all()  # noqa: E712

    for holder in holders:
        cik_padded = holder.cik.lstrip("0").zfill(10)
        logger.info(f"Syncing {holder.name} (CIK {cik_padded})")

        subs = _fetch_submissions(cik_padded)
        if not subs:
            logger.warning(f"No submissions data for {holder.name}")
            continue
        time.sleep(REQUEST_DELAY)

        filing = _latest_13f(subs)
        if not filing:
            logger.info(f"No 13F filing found for {holder.name}")
            continue

        acc_no_dashes, period_str, cik_raw = filing
        quarter = _quarter(period_str)
        if not quarter:
            logger.warning(f"Cannot parse period '{period_str}' for {holder.name}")
            continue

        # Skip if already synced this quarter
        existing = (
            db.query(WhalePosition)
            .filter(WhalePosition.holder_id == holder.id, WhalePosition.quarter == quarter)
            .count()
        )
        if existing > 0:
            logger.info(f"{holder.name} {quarter}: already have {existing} positions — skipping")
            total_skipped += existing
            continue

        xml_url = _find_infotable_url(cik_raw, acc_no_dashes)
        if not xml_url:
            logger.warning(f"Could not find InfoTable XML for {holder.name}")
            continue

        logger.info(f"{holder.name}: fetching {xml_url}")
        time.sleep(REQUEST_DELAY)
        xml_text = _fetch_xml(xml_url)
        if not xml_text:
            continue

        holdings = _parse_infotable(xml_text)
        logger.info(f"{holder.name}: parsed {len(holdings)} holdings for {quarter}")

        try:
            filing_date = datetime.strptime(period_str[:10], "%Y-%m-%d").date()
        except Exception:
            filing_date = date.today()

        count = 0
        unmapped = 0
        for h in holdings[:MAX_POSITIONS]:
            ticker = _lookup_ticker(h["company_name"], ticker_map)
            if not ticker:
                unmapped += 1
                continue

            ct = _change_type(holder.id, ticker, h["value_usd"], db)
            db.add(WhalePosition(
                holder_id=holder.id,
                ticker=ticker,
                company_name=h["company_name"],
                shares=h["shares"],
                value_usd=h["value_usd"],
                filing_date=filing_date,
                quarter=quarter,
                change_type=ct,
            ))
            count += 1

        db.commit()
        total_synced += count
        total_unmapped += unmapped
        logger.info(f"{holder.name}: stored {count} positions ({unmapped} unmapped) for {quarter}")
        time.sleep(REQUEST_DELAY * 2)

    return {"synced": total_synced, "skipped": total_skipped, "unmapped": total_unmapped}
