"""
Fetches corporate-insider Form 4 filings from SEC EDGAR.

Form 4 = a company officer/director/10%-owner reporting a trade in their
own company's stock. We pull these per tracked ticker, parse the ownership
XML, and store non-derivative transactions.

Rate-limit: SEC asks for <=10 req/sec + a User-Agent header.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "InsiderTrack contact@insidertrack.local"}
REQUEST_DELAY = 0.12
MAX_FILINGS_PER_TICKER = 15

_TICKER_CIK_CACHE: dict[str, str] | None = None

# Transaction codes worth surfacing as buy/sell
_BUY_CODES = {"P"}                # open-market / private purchase
_SELL_CODES = {"S"}              # open-market / private sale


def _load_ticker_cik_map() -> dict[str, str]:
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE is not None:
        return _TICKER_CIK_CACHE
    try:
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            r = client.get(COMPANY_TICKERS_URL)
            r.raise_for_status()
            data = r.json()
        mapping: dict[str, str] = {}
        for entry in data.values():
            ticker = (entry.get("ticker") or "").upper().strip()
            cik = entry.get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = str(cik).zfill(10)
        _TICKER_CIK_CACHE = mapping
        logger.info(f"Loaded {len(mapping)} ticker->CIK entries from SEC")
        return mapping
    except Exception as e:
        logger.warning(f"Could not load ticker->CIK map: {e}")
        _TICKER_CIK_CACHE = {}
        return {}


def _fetch_json(url: str) -> Optional[dict]:
    try:
        with httpx.Client(timeout=20, headers=HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning(f"Fetch failed {url}: {e}")
        return None


def _fetch_text(url: str) -> Optional[str]:
    try:
        with httpx.Client(timeout=25, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url)
            if r.status_code == 200:
                return r.text
    except Exception as e:
        logger.warning(f"Fetch failed {url}: {e}")
    return None


def _recent_form4s(submissions: dict) -> list[dict]:
    """Return recent Form 4 filing descriptors from a submissions JSON."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    fdates = recent.get("filingDate", [])
    cik_raw = str(submissions.get("cik", ""))

    out = []
    for i, form in enumerate(forms):
        if form != "4":
            continue
        out.append({
            "accession": accessions[i] if i < len(accessions) else "",
            "primary_doc": docs[i] if i < len(docs) else "",
            "filing_date": fdates[i] if i < len(fdates) else "",
            "cik_raw": cik_raw,
        })
        if len(out) >= MAX_FILINGS_PER_TICKER:
            break
    return out


def _strip_ns(xml_text: str) -> str:
    xml_text = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", xml_text)
    xml_text = re.sub(r"\s+xmlns(?:\w+)?='[^']*'", "", xml_text)
    xml_text = re.sub(r'\s+\w+:\w+="[^"]*"', " ", xml_text)
    xml_text = re.sub(r"<(/?)\w+:", r"<\1", xml_text)
    return xml_text


def _txt(el, path: str) -> str:
    found = el.find(path) if el is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def _parse_form4_xml(xml_text: str) -> Optional[dict]:
    """Parse a Form 4 ownershipDocument XML into a dict of metadata + transactions."""
    cleaned = _strip_ns(xml_text)
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as e:
        logger.warning(f"Form 4 XML parse error: {e}")
        return None

    if not root.tag.lower().endswith("ownershipdocument"):
        return None

    issuer = root.find("issuer")
    company = _txt(issuer, "issuerName")
    symbol = _txt(issuer, "issuerTradingSymbol").upper()

    owner = root.find("reportingOwner")
    insider_name = _txt(owner, "reportingOwnerId/rptOwnerName")
    rel_el = owner.find("reportingOwnerRelationship") if owner is not None else None
    is_director = _txt(rel_el, "isDirector") in ("1", "true")
    is_officer = _txt(rel_el, "isOfficer") in ("1", "true")
    is_ten = _txt(rel_el, "isTenPercentOwner") in ("1", "true")
    officer_title = _txt(rel_el, "officerTitle")

    if is_officer:
        relationship = "Officer"
    elif is_director:
        relationship = "Director"
    elif is_ten:
        relationship = "10% Owner"
    else:
        relationship = "Insider"
    title = officer_title or relationship

    transactions = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        tx_date = _txt(tx, "transactionDate/value")
        code = _txt(tx, "transactionCoding/transactionCode").upper()
        amounts = tx.find("transactionAmounts")
        shares_s = _txt(amounts, "transactionShares/value")
        price_s = _txt(amounts, "transactionPricePerShare/value")
        ad = _txt(amounts, "transactionAcquiredDisposedCode/value").upper()

        try:
            shares = int(float(shares_s)) if shares_s else 0
        except ValueError:
            shares = 0
        try:
            price = float(price_s) if price_s else 0.0
        except ValueError:
            price = 0.0

        if code in _BUY_CODES:
            ttype = "buy"
        elif code in _SELL_CODES:
            ttype = "sell"
        else:
            ttype = "other"

        transactions.append({
            "transaction_date": tx_date,
            "transaction_code": code,
            "transaction_type": ttype,
            "acquired_disposed": ad,
            "shares": shares,
            "price": price,
            "value": int(shares * price),
        })

    return {
        "company_name": company,
        "ticker": symbol,
        "insider_name": insider_name,
        "insider_title": title,
        "relationship": relationship,
        "transactions": transactions,
    }


def _find_form4_doc_url(cik_raw: str, accession: str, primary_doc: str) -> Optional[str]:
    acc_nodash = accession.replace("-", "")
    base = f"{EDGAR_ARCHIVES}/{cik_raw}/{acc_nodash}"
    # primaryDocument for a Form 4 is the XSL-rendered HTML view, often under a
    # path like "xslF345X06/form4.xml". The raw ownership XML lives at the
    # accession root under the same filename.
    if primary_doc.lower().endswith(".xml"):
        return f"{base}/{primary_doc.split('/')[-1]}"
    # Fall back to the directory listing for an ownership XML.
    time.sleep(REQUEST_DELAY)
    listing = _fetch_text(f"{base}/")
    if listing:
        for name in re.findall(r'href="([^"]+\.xml)"', listing, re.IGNORECASE):
            fname = name.split("/")[-1]
            if "xsl" in name.lower():
                continue
            if "form4" in fname.lower() or "ownership" in fname.lower() or fname[0].isalpha():
                return f"{base}/{fname}"
    return None


def sync_form4_for_tickers(db: Session, tickers: list[str]) -> dict:
    """
    For each ticker, pull recent Form 4 filings from EDGAR and store any
    non-derivative transactions not already in the DB.
    """
    from models.insider import Form4Transaction as F4

    ticker_cik = _load_ticker_cik_map()
    time.sleep(REQUEST_DELAY)

    tickers = sorted({t.upper() for t in tickers if t})
    stored = 0
    skipped = 0
    no_cik = 0

    for ticker in tickers:
        cik = ticker_cik.get(ticker)
        if not cik:
            no_cik += 1
            continue

        subs = _fetch_json(f"{EDGAR_SUBMISSIONS}/CIK{cik}.json")
        time.sleep(REQUEST_DELAY)
        if not subs:
            continue

        for filing in _recent_form4s(subs):
            accession = filing["accession"]
            if not accession:
                continue
            existing = db.query(F4).filter(F4.accession == accession).count()
            if existing > 0:
                skipped += 1
                continue

            doc_url = _find_form4_doc_url(filing["cik_raw"], accession, filing["primary_doc"])
            if not doc_url:
                continue
            time.sleep(REQUEST_DELAY)
            xml_text = _fetch_text(doc_url)
            if not xml_text:
                continue

            parsed = _parse_form4_xml(xml_text)
            if not parsed:
                continue

            try:
                fdate = datetime.strptime(filing["filing_date"][:10], "%Y-%m-%d").date()
            except Exception:
                fdate = date.today()

            for tx in parsed["transactions"]:
                if tx["shares"] <= 0:
                    continue
                try:
                    tdate = datetime.strptime(tx["transaction_date"][:10], "%Y-%m-%d").date()
                except Exception:
                    tdate = fdate
                db.add(F4(
                    ticker=parsed["ticker"] or ticker,
                    company_name=parsed["company_name"],
                    insider_name=parsed["insider_name"],
                    insider_title=parsed["insider_title"],
                    relationship=parsed["relationship"],
                    transaction_code=tx["transaction_code"],
                    transaction_type=tx["transaction_type"],
                    shares=tx["shares"],
                    price=tx["price"],
                    value=tx["value"],
                    transaction_date=tdate,
                    filing_date=fdate,
                    accession=accession,
                    source_url=doc_url,
                ))
                stored += 1
            db.commit()

        time.sleep(REQUEST_DELAY)

    logger.info(f"Form 4 sync: {stored} stored, {skipped} skipped, {no_cik} tickers had no CIK")
    return {"stored": stored, "skipped": skipped, "no_cik": no_cik}
