"""
Fetches congressional trade disclosures.

Senate: official Electronic Financial Disclosure (EFD) search at
        https://efdsearch.senate.gov — free, no API key. Returns fully
        structured transaction tables (date, ticker, type, amount).

House:  official Clerk of the House disclosures at
        https://disclosures-clerk.house.gov. The free community mirror
        (house-stock-watcher-data S3 bucket) was taken private in 2026, so we
        go straight to the source: a per-year index ZIP lists every filing, and
        each electronically-filed Periodic Transaction Report (PTR) is a PDF
        with an extractable text layer (ticker, type, dates, amount). Scanned
        paper filings have no text layer and are skipped.
"""

import csv
import io
import json
import logging
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
import pypdf
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from models.app_setting import AppSetting
from models.politician import Politician
from models.processed_filing import ProcessedFiling
from models.trade import Trade
from services import paper_ptr, source_health
from services import trade_semantics as sem

logger = logging.getLogger(__name__)

# ── Senate EFD ────────────────────────────────────────────────────────────────
EFD_BASE = "https://efdsearch.senate.gov"
EFD_HOME = f"{EFD_BASE}/search/home/"
EFD_SEARCH_DATA = f"{EFD_BASE}/search/report/data/"
EFD_PTR_REPORT_TYPE = 11          # "Periodic Transaction Report" in the EFD form
EFD_LOOKBACK_DAYS = 90            # how far back to pull filings each sync
_USER_AGENT = "InsiderTrack/1.0 (congressional disclosure sync; contact via app admin)"

# Electronic PTRs live at /search/view/ptr/<uuid>/ and have a parseable table.
# Paper (scanned) filings live at /search/view/paper/... and have no structured data.
_PTR_LINK_RE = re.compile(r"/search/view/ptr/([0-9a-f-]+)/", re.I)

# ── House Clerk ───────────────────────────────────────────────────────────────
HOUSE_BASE = "https://disclosures-clerk.house.gov"
HOUSE_INDEX_URL = HOUSE_BASE + "/public_disc/financial-pdfs/{year}FD.zip"
HOUSE_PTR_PDF_URL = HOUSE_BASE + "/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
HOUSE_LOOKBACK_DAYS = 90
_HOUSE_TYPE = {"S": "sale", "P": "purchase", "E": "exchange"}

# Transaction line in a House PTR. The two dates print with no separator
# (e.g. "04/16/202605/04/2026") and the amount straddles a dash. We capture
# both listed stocks "[ST]" and options "[OP]" — options name their underlying
# ticker in the same "(TICKER)" form (e.g. "(MSFT) [OP]").
_HOUSE_TXN_RE = re.compile(
    r"\(([A-Z][A-Z.]{0,5})\)\s*\[(ST|OP)\]\s*"  # ticker + asset code
    r"([SPE])\s+"                              # transaction type
    r"(\d{2}/\d{2}/\d{4})\s*"                  # transaction date
    r"(\d{2}/\d{2}/\d{4})\s*"                  # notification (disclosure) date
    r"\$([\d,]+)\s*-\s*\$?([\d,]+)?"           # amount low - high
)
# Each row opens with an optional 10-digit transaction ID and an optional
# owner code (SP spouse / DC dependent child / JT joint; blank = self), often
# glued together ("2000166568SP California ..."). The text before a row also
# holds the previous row's trailer, so we take the LAST id / code before the
# asset name rather than anchoring at the start.
_HOUSE_TXID_RE = re.compile(r"(?<!\d)(20\d{8})(?!\d)")
_HOUSE_OWNER_RE = re.compile(r"(?:^|\d|\s)(SP|DC|JT)(?=\s+[A-Z0-9])")
# Every row carries "Filing Status: New" or "Filing Status: Amended" in its
# trailer (the label letters come out garbled; the value doesn't). An Amended
# row re-files a transaction under the same ID and replaces it.
_HOUSE_STATUS_RE = re.compile(r":\s*(New|Amended)\b")
# Option contracts describe themselves after the amount: "... call options
# with a strike price ..." / "... put option ...". Only the segment up to the
# next transaction belongs to this row.
_HOUSE_OPTION_KIND_RE = re.compile(r"\b(call|put)s?\b", re.I)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ── Sync status (in-memory, for the UI to poll) ───────────────────────────────
# sync_all() updates this so a backgrounded /trades/sync can be tracked without
# blocking the request. Single-process app, so a module global is sufficient.
_sync_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "result": None,     # {"house": int, "senate": int}
    "error": None,
}


def get_sync_state() -> dict:
    return dict(_sync_state)


# ── Legislator directory (party / state enrichment) ───────────────────────────
# Free roster from the unitedstates/congress-legislators project; maps a
# member's name to party + home state, which neither the House index nor the
# EFD search rows include. Cached in-process and refreshed daily.
LEGISLATORS_URL = "https://unitedstates.github.io/congress-legislators/legislators-current.csv"
_PARTY_ABBR = {"Democrat": "D", "Republican": "R", "Independent": "I"}
_legislators: dict[str, tuple[str, str]] = {}   # "first last" → (party, state)
_legislators_loaded_on: Optional[date] = None


_HONORIFICS = ("hon", "mr", "mrs", "ms", "dr", "rep", "sen")
_SUFFIXES = ("jr", "sr", "ii", "iii", "iv", "v")


def _norm_name(first: str, last: str) -> str:
    """Normalize to 'firsttoken lasttoken', lowercased, punctuation stripped —
    so 'Hon. Richard W. Allen' and 'Richard Allen' collide, and a trailing
    suffix ('Kean Jr') doesn't get mistaken for the surname."""
    first = re.sub(r"[^a-z ]", "", (first or "").lower()).split()
    last = re.sub(r"[^a-z ]", "", (last or "").lower()).split()
    # drop honorific prefixes that sometimes ride along in the first name
    first = [t for t in first if t not in _HONORIFICS]
    # drop generational suffixes that sometimes ride along in the last name
    last = [t for t in last if t not in _SUFFIXES]
    f = first[0] if first else ""
    l = last[-1] if last else ""
    return f"{f} {l}".strip()


def _load_legislators() -> dict[str, tuple[str, str]]:
    global _legislators, _legislators_loaded_on
    if _legislators and _legislators_loaded_on == date.today():
        return _legislators
    try:
        resp = httpx.get(LEGISLATORS_URL, timeout=30, follow_redirects=True,
                         headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        directory: dict[str, tuple[str, str]] = {}
        for row in csv.DictReader(io.StringIO(resp.text)):
            party = _PARTY_ABBR.get((row.get("party") or "").strip(), "")
            state = (row.get("state") or "").strip()
            key = _norm_name(row.get("first_name", ""), row.get("last_name", ""))
            if key.strip():
                directory[key] = (party, state)
        if directory:
            _legislators = directory
            _legislators_loaded_on = date.today()
            logger.info(f"Loaded {len(directory)} legislators for party/state enrichment")
    except Exception as exc:
        logger.warning(f"Legislator directory unavailable: {exc}")
    return _legislators


def _enrich(first: str, last: str) -> tuple[str, str]:
    """Best-effort (party, state) for a member; empty strings if not matched."""
    return _load_legislators().get(_norm_name(first, last), ("", ""))


def _get_or_create_politician(db: Session, name: str, chamber: str, party: str = "", state: str = "") -> Politician:
    politician = db.query(Politician).filter(Politician.name == name).first()
    if not politician:
        politician = Politician(name=name, chamber=chamber, party=party, state=state, is_tracked=True)
        db.add(politician)
        db.flush()
        return politician
    # Backfill party/state for rows created before enrichment existed.
    if party and not (politician.party or "").strip():
        politician.party = party
    if state and not (politician.state or "").strip():
        politician.state = state
    return politician


def _find_trade(db: Session, politician_id: int, ticker: str, trade_date: date,
                tx_type: str, amount: str) -> Optional[Trade]:
    """Dedup key for a filing row. The amount bracket is part of the key: a
    member can legitimately report two lots of the same ticker on the same
    day, and they differ only by amount."""
    return db.query(Trade).filter(
        Trade.politician_id == politician_id,
        Trade.ticker == ticker,
        Trade.trade_date == trade_date,
        Trade.transaction_type == tx_type,
        Trade.amount_range == amount,
    ).first()


def _trade_exists(db: Session, politician_id: int, ticker: str, trade_date: date,
                  tx_type: str, amount: str) -> bool:
    return _find_trade(db, politician_id, ticker, trade_date, tx_type, amount) is not None


def _refresh_trade(t: Trade, tx: dict, disclosure_date: Optional[date], raw: dict,
                   filing_id: Optional[str], amends: Optional[date]) -> None:
    """Re-parse mode: bring an existing row's derived columns up to what the
    current parser extracts (owner, call/put, amount bounds, direction,
    provenance). The row keeps its id so alert events and links survive."""
    asset_type = tx.get("asset_type") or sem.ASSET_STOCK
    low, high = sem.parse_amount_range(tx.get("amount"))
    t.asset_name = tx.get("asset_name", "") or t.asset_name
    t.amount_low, t.amount_high = low, high
    t.owner = tx.get("owner") or sem.OWNER_SELF
    t.asset_type = asset_type
    t.direction = sem.direction(t.transaction_type, asset_type, tx.get("asset_name"))
    t.disclosure_date = disclosure_date or t.disclosure_date
    t.filing_id = filing_id or t.filing_id
    t.amends = amends
    t.house_tx_id = tx.get("tx_id") or t.house_tx_id
    t.raw_data = json.dumps(raw)


def _drop_stale_filing_rows(db: Session, filing_id: str, keep_ids: set[int]) -> int:
    """Re-parse mode: rows from this filing that the current parser no longer
    produces (e.g. a now-rejected implausible date) are removed."""
    q = db.query(Trade).filter(Trade.filing_id == filing_id)
    if keep_ids:
        q = q.filter(Trade.id.notin_(keep_ids))
    return q.delete(synchronize_session=False)


# Filers typo dates ("12/26/2026" for a trade disclosed in January 2026,
# "03/28/1935" as a notification date). A trade can't happen after it was
# disclosed or in the future, and nothing electronic predates the STOCK Act.
_EARLIEST_PLAUSIBLE = date(2012, 1, 1)


def _plausible_trade_date(trade_date: date, disclosure_date: Optional[date]) -> bool:
    if trade_date > date.today() or trade_date < _EARLIEST_PLAUSIBLE:
        return False
    if disclosure_date and disclosure_date >= _EARLIEST_PLAUSIBLE and trade_date > disclosure_date + timedelta(days=1):
        return False
    return True


def _new_trade(politician_id: int, tx: dict, tx_type: str, trade_date: date,
               disclosure_date: Optional[date], source: str, raw: dict,
               filing_id: Optional[str] = None, amends: Optional[date] = None) -> Trade:
    """Build a Trade with the derived columns (owner, asset_type, direction,
    amount bounds) filled from the parsed filing row."""
    asset_type = tx.get("asset_type") or sem.ASSET_STOCK
    low, high = sem.parse_amount_range(tx.get("amount"))
    return Trade(
        politician_id=politician_id,
        ticker=tx["ticker"],
        asset_name=tx.get("asset_name", ""),
        transaction_type=tx_type,
        amount_range=tx.get("amount", ""),
        amount_low=low,
        amount_high=high,
        owner=tx.get("owner") or sem.OWNER_SELF,
        asset_type=asset_type,
        direction=sem.direction(tx_type, asset_type, tx.get("asset_name")),
        trade_date=trade_date,
        disclosure_date=disclosure_date,
        source=source,
        filing_id=filing_id,
        amends=amends,
        house_tx_id=tx.get("tx_id"),
        raw_data=json.dumps(raw),
    )


# ── Processed-filing bookkeeping (skip re-downloads) ──────────────────────────
def _load_processed(db: Session, source: str) -> set[str]:
    return {
        doc for (doc,) in db.query(ProcessedFiling.doc_id)
        .filter(ProcessedFiling.source == source).all()
    }


def _mark_processed(db: Session, source: str, doc_id: str) -> None:
    db.add(ProcessedFiling(source=source, doc_id=doc_id))


def _mark_processed_once(db: Session, source: str, doc_id: str) -> None:
    """Record the filing unless it already is — re-parse runs revisit
    filings that were marked long ago, and (source, doc_id) is unique."""
    hit = db.query(ProcessedFiling.id).filter(
        ProcessedFiling.source == source, ProcessedFiling.doc_id == doc_id).first()
    if not hit:
        _mark_processed(db, source, doc_id)


def _request_with_retry(fn, *, retries: int = 3, backoff: float = 1.5, label: str = "request"):
    """Call an httpx request `fn`, retrying on transient failures and 429s with
    exponential backoff. EFD rate-limits aggressively, so a single blip
    shouldn't zero out a whole sync. Re-raises after the final attempt."""
    for attempt in range(retries):
        try:
            resp = fn()
            if resp.status_code in (429, 500, 502, 503):
                raise httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < retries - 1:
                sleep = backoff * (2 ** attempt)
                logger.info(f"{label} attempt {attempt + 1}/{retries} failed ({e}); retrying in {sleep:.1f}s")
                time.sleep(sleep)
                continue
            logger.warning(f"{label} failed after {retries} attempts: {e}")
            raise
    return None  # unreachable


# ── EFD session handling ──────────────────────────────────────────────────────
def _efd_client() -> httpx.Client:
    """Open an EFD session and accept the prohibition-on-use agreement.

    The search endpoints return nothing until the agreement cookie is set, so
    every session must: GET the home page (seeds the csrftoken cookie) then
    POST the agreement back.
    """
    client = httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT, "Referer": EFD_HOME},
    )
    client.get(EFD_HOME)
    token = client.cookies.get("csrftoken", "")
    client.post(
        EFD_HOME,
        data={"prohibition_agreement": "1", "csrfmiddlewaretoken": token},
        headers={"Referer": EFD_HOME},
    )
    return client


def _fetch_ptr_list(client: httpx.Client, start_date: date, end_date: Optional[date] = None) -> list[dict]:
    """Page through the EFD search API for Senate PTRs filed between
    `start_date` and `end_date` (inclusive; open-ended when None)."""
    token = client.cookies.get("csrftoken", "")
    headers = {
        "Referer": f"{EFD_BASE}/search/",
        "X-CSRFToken": token,
        "X-Requested-With": "XMLHttpRequest",
    }
    reports: list[dict] = []
    offset, page_size = 0, 100
    while True:
        payload = {
            "start": str(offset),
            "length": str(page_size),
            "report_types": f"[{EFD_PTR_REPORT_TYPE}]",
            "filer_types": "[]",
            "submitted_start_date": start_date.strftime("%m/%d/%Y 00:00:00"),
            "submitted_end_date": end_date.strftime("%m/%d/%Y 23:59:59") if end_date else "",
            "candidate_state": "",
            "senator_state": "",
            "office_id": "",
            "first_name": "",
            "last_name": "",
            "csrfmiddlewaretoken": token,
        }
        resp = _request_with_retry(
            lambda: client.post(EFD_SEARCH_DATA, data=payload, headers=headers),
            label="EFD search",
        )
        body = resp.json()
        rows = body.get("data", [])
        for row in rows:
            # row = [first, last, "Last, First (Senator)", "<a href=...>Report...</a>", "MM/DD/YYYY"]
            link_html = row[3] if len(row) > 3 else ""
            m = _PTR_LINK_RE.search(link_html)
            if not m:
                continue  # paper/scanned filing — no structured transactions
            reports.append({
                "first": (row[0] or "").strip(),
                "last": (row[1] or "").strip(),
                "uuid": m.group(1),
                "filed": (row[4] or "").strip() if len(row) > 4 else "",
                # Amended reports carry "(Amendment N)" in the link title.
                "amended": "mendment" in link_html,
            })
        total = body.get("recordsTotal", 0)
        offset += page_size
        if offset >= total or not rows:
            break
        time.sleep(0.5)  # be polite to a government endpoint
    return reports


def _parse_senate_rows(html: str) -> list[dict]:
    """Parse the transaction table out of a Senate PTR detail page.

    Kept separate from the HTTP fetch so it can be unit-tested on HTML fixtures.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    # Map header label → column index so we are robust to column reordering.
    # Prefer an exact header match before a substring one — the EFD table has
    # both an "Asset Type" column (e.g. "Stock") and a "Type" column (the
    # Purchase/Sale we actually want), and "type" is a substring of both.
    headers = [th.get_text(strip=True).lower() for th in table.select("thead th")]
    def col(label: str) -> Optional[int]:
        for i, h in enumerate(headers):
            if h == label:
                return i
        for i, h in enumerate(headers):
            if label in h:
                return i
        return None

    i_date, i_ticker, i_type, i_amount, i_asset, i_owner, i_asset_type = (
        col("transaction date"), col("ticker"), col("type"), col("amount"), col("asset name"),
        col("owner"), col("asset type"),
    )
    txns = []
    for tr in table.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells or i_ticker is None:
            continue
        ticker = (cells[i_ticker] if i_ticker < len(cells) else "").strip()
        if not ticker or ticker in ("--", "N/A", "—"):
            continue
        def cell(i: Optional[int]) -> str:
            return cells[i] if i is not None and i < len(cells) else ""
        txns.append({
            "transaction_date": cell(i_date),
            "ticker": ticker,
            "type": cell(i_type).strip(),
            "amount": cell(i_amount),
            "asset_name": cell(i_asset),
            "asset_type": sem.normalize_asset_type(cell(i_asset_type)),
            "owner": sem.normalize_owner(cell(i_owner)),
        })
    return txns


# "Periodic Transaction Report for 12/08/2025 (Amendment 1)" — the date is
# the filing date of the report being amended (for an original it's its own).
_SENATE_TITLE_RE = re.compile(r"Periodic Transaction Report\s+for\s+(\d{2}/\d{2}/\d{4})", re.I)


def _parse_senate_report_date(html: str) -> Optional[date]:
    m = _SENATE_TITLE_RE.search(re.sub(r"\s+", " ", html))
    return _parse_date(m.group(1)) if m else None


def _fetch_ptr_transactions(client: httpx.Client, uuid: str) -> tuple[Optional[date], list[dict]]:
    """Fetch one electronic Senate PTR detail page → (report "for" date, transactions)."""
    resp = _request_with_retry(
        lambda: client.get(f"{EFD_BASE}/search/view/ptr/{uuid}/"),
        label=f"EFD PTR {uuid}",
    )
    return _parse_senate_report_date(resp.text), _parse_senate_rows(resp.text)


def supersede_senate_report(db: Session, politician_id: int, original_filed: date, amendment_id: str) -> int:
    """An amendment replaces the whole report: drop the original's rows
    (filed on `original_filed`) and any earlier amendment of it. Returns the
    number of rows removed."""
    q = db.query(Trade).filter(
        Trade.politician_id == politician_id,
        Trade.source == "senate",
        Trade.filing_id != amendment_id,
        ((Trade.amends.is_(None)) & (Trade.disclosure_date == original_filed))
        | (Trade.amends == original_filed),
    )
    n = q.delete(synchronize_session=False)
    if n:
        logger.info(f"Senate amendment {amendment_id} supersedes report of {original_filed}: removed {n} row(s)")
    return n


def _senate_report_superseded(db: Session, politician_id: int, filed: date) -> bool:
    """True if an amendment of this senator's report filed on `filed` is
    already stored — the original then must not be (re)inserted."""
    return db.query(Trade.id).filter(
        Trade.politician_id == politician_id,
        Trade.source == "senate",
        Trade.amends == filed,
    ).first() is not None


def sync_senate_trades(db: Session, start_date: Optional[date] = None,
                       end_date: Optional[date] = None, progress=None,
                       reparse: bool = False) -> int:
    """Import Senate PTRs filed in [start_date, end_date]. Defaults to the
    rolling EFD_LOOKBACK_DAYS window; the backfill passes explicit bounds.
    `progress(done, total)` is called per filing when given. With `reparse`,
    already-processed filings are fetched again and their rows refreshed in
    place (new columns, better parsing) instead of being skipped."""
    start_date = start_date or date.today() - timedelta(days=EFD_LOOKBACK_DAYS)
    logger.info(f"Fetching Senate trades from EFD ({start_date} → {end_date or 'now'}{', re-parse' if reparse else ''})...")

    client = _efd_client()
    seen = set() if reparse else _load_processed(db, "senate")
    try:
        reports = _fetch_ptr_list(client, start_date, end_date)
        new_reports = [r for r in reports if r["uuid"] not in seen]
        logger.info(f"EFD: {len(reports)} PTRs since {start_date}, {len(new_reports)} new")

        count = 0
        for i, rpt in enumerate(new_reports):
                if progress:
                    progress(i, len(new_reports))
                name = f"{rpt['first']} {rpt['last']}".strip()
                if not name:
                    continue
                filed = _parse_date(rpt["filed"])
                try:
                    report_for, txns = _fetch_ptr_transactions(client, rpt["uuid"])
                except Exception as exc:  # one bad filing shouldn't abort the sync
                    logger.warning(f"EFD PTR {rpt['uuid']} failed: {exc}")
                    report_for, txns = None, []
                time.sleep(0.6)  # rate-limit detail-page fetches

                party, state = _enrich(rpt["first"], rpt["last"])
                politician = _get_or_create_politician(db, name, "senate", party=party, state=state)

                # Amendments replace the report they amend. The trades were
                # public from the original filing, so that stays the
                # disclosure date; the amendment's own date lives in raw_data.
                amends = None
                disclosure_date = filed
                if rpt.get("amended") and report_for:
                    amends = report_for
                    disclosure_date = report_for
                    supersede_senate_report(db, politician.id, report_for, rpt["uuid"])
                elif not rpt.get("amended") and filed and _senate_report_superseded(db, politician.id, filed):
                    logger.info(f"EFD PTR {rpt['uuid']} ({name}, {filed}) already superseded by an amendment — skipped")
                    _mark_processed_once(db, "senate", rpt["uuid"])
                    db.commit()
                    continue

                kept: set[int] = set()
                for tx in txns:
                    trade_date = _parse_date(tx["transaction_date"])
                    if not trade_date:
                        continue
                    if not _plausible_trade_date(trade_date, disclosure_date):
                        logger.warning(f"EFD {rpt['uuid']}: skipping {tx['ticker']} with implausible trade date {trade_date} (filed {disclosure_date})")
                        continue
                    tx_type = tx["type"].lower()
                    raw = {**tx, "ptr_uuid": rpt["uuid"], "amended": rpt.get("amended", False),
                           "amendment_filed": rpt["filed"] if amends else None}
                    existing = _find_trade(db, politician.id, tx["ticker"], trade_date, tx_type, tx["amount"])
                    if existing:
                        if reparse:
                            _refresh_trade(existing, tx, disclosure_date, raw, rpt["uuid"], amends)
                            kept.add(existing.id)
                        continue
                    t = _new_trade(politician.id, tx, tx_type, trade_date, disclosure_date, "senate", raw,
                                   filing_id=rpt["uuid"], amends=amends)
                    db.add(t)
                    db.flush()  # autoflush is off — make this row visible to the next exists-check
                    kept.add(t.id)
                    count += 1
                if reparse:
                    _drop_stale_filing_rows(db, rpt["uuid"], kept)
                _mark_processed_once(db, "senate", rpt["uuid"])
                db.commit()
    except Exception as exc:
        # Rows committed per filing are kept; the caller records the failure
        # (source_health) so a broken scraper is distinguishable from a quiet week.
        logger.error(f"Senate EFD sync failed: {exc}")
        db.rollback()
        raise
    finally:
        client.close()

    logger.info(f"Synced {count} new Senate trades")
    return count


def _fetch_house_index(client: httpx.Client, year: int) -> list[dict]:
    """Download and parse the House Clerk per-year filing index (tab-delimited)."""
    resp = client.get(HOUSE_INDEX_URL.format(year=year))
    resp.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    raw = archive.read(f"{year}FD.txt").decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(raw), delimiter="\t"))


def _parse_house_text(text: str) -> list[dict]:
    """Pull listed-stock and option transactions out of a PTR's extracted text.

    Kept separate from PDF reading so it can be unit-tested on text fixtures.
    """
    flat = re.sub(r"\s+", " ", text)  # PTR rows wrap across lines; flatten first
    amended = bool(re.search(r"\bamendment\b", flat, re.I))
    matches = list(_HOUSE_TXN_RE.finditer(flat))
    txns = []
    for i, m in enumerate(matches):
        tk, code, ty, td, nd, lo, hi = m.groups()
        is_option = code == "OP"
        # Text owned by this row: from the end of the previous match to the
        # start of the next one. The owner code sits at its head, an option's
        # call/put description in its tail.
        head = flat[matches[i - 1].end() if i else 0 : m.start()]
        tail = flat[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(flat)]
        # Only the last ~160 chars of head belong to this row's prefix; the
        # previous row's trailer ("... O: Some Trust ...") sits before that.
        prefix = head[-160:]
        ids = _HOUSE_TXID_RE.findall(prefix)
        tx_id = ids[-1] if ids else None
        owners = _HOUSE_OWNER_RE.findall(prefix[prefix.rfind(tx_id) if tx_id else 0:] if tx_id else prefix)
        owner_code = owners[-1] if owners else ""
        status_m = _HOUSE_STATUS_RE.search(tail)
        kind_m = _HOUSE_OPTION_KIND_RE.search(tail) if is_option else None
        kind = kind_m.group(1).lower() if kind_m else None
        txns.append({
            "ticker": tk,
            "type": _HOUSE_TYPE.get(ty, ty.lower()),
            "transaction_date": td,
            "disclosure_date": nd,
            "amount": f"${lo} - ${hi}" if hi else f"${lo}",
            "asset_type": "option" if is_option else "stock",
            "asset_name": (f"{tk} {kind} option" if kind else f"{tk} (option)") if is_option else "",
            "owner": sem.normalize_owner(owner_code),
            "tx_id": tx_id,
            "status": (status_m.group(1).lower() if status_m else "new"),
            "amended": amended or (status_m is not None and status_m.group(1) == "Amended"),
        })
    return txns


def paper_ptr_enabled() -> bool:
    """Paper filings are read by the site's AI provider; nothing to do without one."""
    from services.providers import active_provider
    try:
        return active_provider() is not None
    except Exception:
        return False


_house_ticker_map: Optional[dict] = None


def _house_ticker_lookup():
    """Company-name → ticker resolver for paper filings ('Provide full name,
    not ticker symbol'). Reuses the 13F fetcher's SEC name map."""
    global _house_ticker_map
    from services.edgar_fetcher import _load_ticker_map, _lookup_ticker
    if _house_ticker_map is None:
        try:
            _house_ticker_map = _load_ticker_map()
        except Exception as exc:
            logger.warning(f"ticker map unavailable for paper PTRs: {exc}")
            _house_ticker_map = {}
    m = _house_ticker_map
    return lambda name: _lookup_ticker(name, m) if name else ""


def _is_known_ticker(sym: str) -> bool:
    """Is `sym` a symbol in SEC's company list? Guards bare tokens read off
    a paper form ("ETF" is not a ticker; "TLH" is)."""
    from services.form4_fetcher import _load_ticker_cik_map
    try:
        return sym in _load_ticker_cik_map()
    except Exception:
        return False


def tx_disclosure_fallback(txns: list[dict]) -> Optional[str]:
    """Notification date from the first parsed row — only used when the
    Clerk's index row has no FilingDate."""
    return txns[0].get("disclosure_date") if txns else None


def _parse_house_ptr(pdf_bytes: bytes) -> list[dict]:
    """Extract listed-stock transactions from one electronically-filed PTR PDF."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_house_text(text)


def sync_house_trades(db: Session, start_date: Optional[date] = None,
                      end_date: Optional[date] = None, progress=None,
                      reparse: bool = False) -> int:
    """Pull House PTRs filed in [start_date, end_date] from the Clerk's office
    and parse their PDFs. Defaults to the rolling HOUSE_LOOKBACK_DAYS window;
    the backfill passes explicit bounds.

    Electronically-filed PTRs (DocID begins with "2") carry a text layer and
    are parsed directly. Paper filings (scanned, often handwritten) are read
    by the configured vision model — see services.paper_ptr — up to
    PAPER_MAX_PER_RUN per sync, and stored with source="house-paper". Filings
    already imported (tracked by DocID) are not re-downloaded.
    `progress(done, total)` is called per filing when given.
    """
    cutoff = start_date or date.today() - timedelta(days=HOUSE_LOOKBACK_DAYS)
    until = end_date or date.today()
    logger.info(f"Fetching House trades from Clerk disclosures ({cutoff} → {until}{', re-parse' if reparse else ''})...")
    years = list(range(cutoff.year, until.year + 1))

    # DocIDs we've already parsed (incl. filings with no listed-stock trades), so
    # re-syncs don't re-download the same PDFs. Re-parse mode ignores this and
    # refreshes the stored rows in place.
    processed = _load_processed(db, "house")
    seen = set() if reparse else set(processed)

    count = 0
    client = httpx.Client(timeout=60, follow_redirects=True,
                          headers={"User-Agent": _USER_AGENT})
    try:
        for year in years:
            try:
                rows = _fetch_house_index(client, year)
            except Exception as exc:
                logger.warning(f"House index {year} unavailable: {exc}")
                continue

            # Filter first so progress totals are meaningful.
            todo = []
            paper_budget = paper_ptr.PAPER_MAX_PER_RUN if paper_ptr_enabled() else 0
            for row in rows:
                doc_id = (row.get("DocID") or "").strip()
                # FilingType "P" = Periodic Transaction Report; DocID starting
                # with "2" marks an electronic (text-layer) filing, anything
                # else a scanned paper form.
                if row.get("FilingType") != "P":
                    continue
                if doc_id in seen:
                    continue
                filed = _parse_date(row.get("FilingDate"))
                if filed and (filed < cutoff or filed > until):
                    continue
                if not doc_id.startswith("2"):
                    if paper_budget <= 0 or reparse:
                        continue        # paper: only within budget, never in re-parse
                    paper_budget -= 1
                todo.append((row, doc_id))

            for i, (row, doc_id) in enumerate(todo):
                if progress:
                    progress(i, len(todo))

                first, last = (row.get("First") or "").strip(), (row.get("Last") or "").strip()
                name = f"{first} {last}".strip()
                if not name:
                    continue

                is_paper = not doc_id.startswith("2")
                try:
                    pdf = client.get(HOUSE_PTR_PDF_URL.format(year=year, doc_id=doc_id))
                    if pdf.status_code != 200:
                        continue  # transient/missing — retry on a later sync
                    if is_paper:
                        reading = paper_ptr.read_paper_ptr(pdf.content)
                        if reading is None:
                            continue  # provider down / no JSON — not marked processed, retried next sync
                        txns, pstats = paper_ptr.rows_from_reading(reading, _house_ticker_lookup(), _is_known_ticker)
                        logger.info(f"House paper PTR {doc_id} ({name}): {pstats} via {reading.get('_model')}")
                    else:
                        txns = _parse_house_ptr(pdf.content)
                except Exception as exc:  # a single bad PDF must not abort the sync
                    logger.warning(f"House PTR {doc_id} failed: {exc}")
                    txns = []
                time.sleep(0.4)  # be polite to a government endpoint

                # State from the filing (e.g. "GA12" → "GA"); party from the roster.
                party, roster_state = _enrich(first, last)
                state = (row.get("StateDst") or "")[:2] or roster_state
                politician = _get_or_create_politician(db, name, "house", party=party, state=state)

                # Disclosure = the Clerk's filing date (when the public could
                # see it). The PTR's own "notification date" is hand-typed and
                # sometimes nonsense (1935); it stays in raw_data only.
                filed = _parse_date(row.get("FilingDate")) or _parse_date(tx_disclosure_fallback(txns))
                kept: set[int] = set()
                for tx in txns:
                    trade_date = _parse_date(tx["transaction_date"])
                    if not trade_date:
                        continue
                    if not _plausible_trade_date(trade_date, filed):
                        logger.warning(f"House PTR {doc_id}: skipping {tx['ticker']} with implausible trade date {trade_date} (filed {filed})")
                        continue
                    raw = {**tx, "ptr_doc_id": doc_id, "filing_date": row.get("FilingDate"),
                           **({"paper": True, "model": reading.get("_model")} if is_paper else {})}
                    # The transaction ID is the real identity of a House row.
                    # An "Amended" row with a known ID replaces the earlier
                    # version in place (same trade id); a "New" row with a
                    # known ID is a re-download of the same filing.
                    existing = None
                    if tx.get("tx_id"):
                        existing = db.query(Trade).filter(
                            Trade.politician_id == politician.id, Trade.house_tx_id == tx["tx_id"]).first()
                    if existing is None:
                        existing = _find_trade(db, politician.id, tx["ticker"], trade_date, tx["type"], tx["amount"])
                    if existing:
                        if tx.get("status") == "amended" and existing.filing_id != doc_id:
                            original_filed = existing.disclosure_date
                            existing.ticker = tx["ticker"]
                            existing.transaction_type = tx["type"]
                            existing.trade_date = trade_date
                            existing.amount_range = tx["amount"]
                            _refresh_trade(existing, tx, original_filed, raw, doc_id, original_filed)
                            logger.info(f"House PTR {doc_id}: amended transaction {tx.get('tx_id')} replaced in place")
                        elif reparse:
                            _refresh_trade(existing, tx, filed, raw, doc_id, existing.amends)
                        kept.add(existing.id)
                        continue
                    t = _new_trade(politician.id, tx, tx["type"], trade_date, filed,
                                   "house-paper" if is_paper else "house", raw, filing_id=doc_id)
                    db.add(t)
                    db.flush()  # autoflush is off — make this row visible to the next exists-check
                    kept.add(t.id)
                    count += 1
                if reparse:
                    _drop_stale_filing_rows(db, doc_id, kept)
                seen.add(doc_id)
                if doc_id not in processed:
                    _mark_processed_once(db, "house", doc_id)
                    processed.add(doc_id)
                db.commit()
    except Exception as exc:
        logger.error(f"House sync failed: {exc}")
        db.rollback()
        raise
    finally:
        client.close()

    logger.info(f"Synced {count} new House trades")
    return count


def repair_house_disclosure_dates(db: Session) -> int:
    """Fill disclosure_date on House rows that lack one (rows imported before
    the sync used the Clerk's filing date, then NULLed by the date-cleanup
    migration) from the per-year index. One ZIP per year involved."""
    rows = (
        db.query(Trade)
        .filter(Trade.source == "house", Trade.disclosure_date.is_(None))
        .all()
    )
    if not rows:
        return 0
    by_doc: dict[str, list[Trade]] = {}
    for t in rows:
        try:
            doc_id = str(json.loads(t.raw_data or "{}").get("ptr_doc_id") or "")
        except ValueError:
            doc_id = ""
        if doc_id:
            by_doc.setdefault(doc_id, []).append(t)
    if not by_doc:
        return 0
    years = sorted({t.trade_date.year for ts in by_doc.values() for t in ts} | {date.today().year})
    filed_by_doc: dict[str, Optional[date]] = {}
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    try:
        for year in years:
            try:
                for row in _fetch_house_index(client, year):
                    doc = (row.get("DocID") or "").strip()
                    if doc in by_doc:
                        filed_by_doc[doc] = _parse_date(row.get("FilingDate"))
            except Exception as exc:
                logger.warning(f"House index {year} unavailable during repair: {exc}")
    finally:
        client.close()
    fixed = 0
    for doc, trades in by_doc.items():
        filed = filed_by_doc.get(doc)
        if not filed:
            continue
        for t in trades:
            t.disclosure_date = filed
            fixed += 1
    db.commit()
    logger.info(f"Repaired disclosure_date on {fixed} House trade(s)")
    return fixed


def repair_senate_amendments(db: Session) -> dict:
    """Apply the supersede rule to amended reports stored before `amends`
    existed. Re-reads each such report's title from EFD to learn which
    filing it amends (one page per amended report)."""
    rows = (
        db.query(Trade)
        .filter(Trade.source == "senate", Trade.amends.is_(None),
                Trade.raw_data.like('%"amended": true%'))
        .all()
    )
    by_uuid: dict[str, list[Trade]] = {}
    for t in rows:
        if t.filing_id:
            by_uuid.setdefault(t.filing_id, []).append(t)
    if not by_uuid:
        return {"reports": 0, "removed": 0}
    client = _efd_client()
    removed = fixed_reports = 0
    try:
        for uuid, trades in by_uuid.items():
            try:
                report_for, _ = _fetch_ptr_transactions(client, uuid)
            except Exception as exc:
                logger.warning(f"EFD PTR {uuid} unavailable during amendment repair: {exc}")
                continue
            time.sleep(0.6)
            if not report_for:
                continue
            pid = trades[0].politician_id
            removed += supersede_senate_report(db, pid, report_for, uuid)
            for t in trades:
                t.amends = report_for
                t.disclosure_date = report_for
            fixed_reports += 1
            db.commit()
    finally:
        client.close()
    logger.info(f"Senate amendment repair: {fixed_reports} report(s), {removed} superseded row(s) removed")
    return {"reports": fixed_reports, "removed": removed}


# ── Historical backfill ───────────────────────────────────────────────────────
# The rolling sync only looks back ~90 days. This walks an explicit range
# (House: per-year index ZIPs; Senate: EFD date-bounded search) so the
# simulator, outcomes and per-member track records have history to work
# with. Idempotent: processed filings and the trade dedup key make re-runs
# cheap. Slow by design (one government PDF per filing, politely paced) —
# run it in the background and poll get_backfill_state().

_BACKFILL_KEY = "congress_backfill"
_backfill_state: dict = {"running": False}


def get_backfill_state(db: Optional[Session] = None) -> dict:
    """In-memory state while running; the persisted last outcome otherwise."""
    if _backfill_state.get("running") or db is None:
        return dict(_backfill_state)
    row = db.query(AppSetting).filter(AppSetting.key == _BACKFILL_KEY).first()
    if row and row.value:
        try:
            return {**json.loads(row.value), "running": False}
        except ValueError:
            pass
    return dict(_backfill_state)


def backfill(db: Session, since: date, until: Optional[date] = None, reparse: bool = False) -> dict:
    """Import every electronic PTR filed in [since, until] from both chambers.
    With `reparse`, filings already imported are fetched again and their rows
    refreshed in place — the way to pick up parser improvements (owner,
    call/put, amount bounds) on history."""
    until = until or date.today()
    if _backfill_state.get("running"):
        raise RuntimeError("A backfill is already running")
    _backfill_state.clear()
    _backfill_state.update(running=True, since=since.isoformat(), until=until.isoformat(),
                           reparse=reparse,
                           started_at=datetime.now().isoformat(), finished_at=None,
                           phase=None, done=0, total=0, result={}, error=None)

    def _progress(phase):
        def cb(done, total):
            _backfill_state.update(phase=phase, done=done, total=total)
        return cb

    result: dict = {}
    errors: dict = {}
    try:
        for name, fn in (("senate", sync_senate_trades), ("house", sync_house_trades)):
            _backfill_state.update(phase=name, done=0, total=0)
            try:
                result[name] = fn(db, start_date=since, end_date=until, progress=_progress(name), reparse=reparse)
                source_health.record(db, name, ok=True, new_rows=result[name],
                                     detail={"backfill": f"{since} → {until}"})
            except Exception as exc:
                result[name] = 0
                errors[name] = str(exc)
                logger.error(f"Backfill {name} failed: {exc}")
                source_health.record(db, name, ok=False, error=str(exc))
        if errors:
            result["errors"] = errors
        try:
            repair_house_disclosure_dates(db)
        except Exception as exc:
            logger.warning(f"disclosure_date repair after backfill failed: {exc}")
        try:
            repair_senate_amendments(db)
        except Exception as exc:
            logger.warning(f"Senate amendment repair after backfill failed: {exc}")
        # New rows need a staleness bucket; the daily job would get there
        # eventually but the feed filters on it immediately.
        try:
            from routers.trades import refresh_risk_levels
            refresh_risk_levels(db)
        except Exception as exc:
            logger.warning(f"risk_level refresh after backfill failed: {exc}")
        return result
    finally:
        _backfill_state.update(running=False, finished_at=datetime.now().isoformat(),
                               result=result, error="; ".join(f"{k}: {v}" for k, v in errors.items()) or None)
        try:
            row = db.query(AppSetting).filter(AppSetting.key == _BACKFILL_KEY).first()
            payload = json.dumps({k: v for k, v in _backfill_state.items() if k != "running"})
            if row:
                row.value = payload
            else:
                db.add(AppSetting(key=_BACKFILL_KEY, value=payload))
            db.commit()
        except Exception as exc:
            logger.warning(f"Could not persist backfill record: {exc}")
            db.rollback()


_LAST_SYNC_KEY = "congress_last_sync"


def _persist_last_sync(db: Session, payload: dict) -> None:
    """Record the most recent sync outcome so it survives restarts and the 8 AM
    scheduler run is auditable (the in-memory _sync_state resets on restart)."""
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _LAST_SYNC_KEY).first()
        value = json.dumps(payload)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=_LAST_SYNC_KEY, value=value))
        db.commit()
    except Exception as exc:
        logger.warning(f"Could not persist last-sync record: {exc}")
        db.rollback()


def get_last_sync(db: Session) -> Optional[dict]:
    """The last persisted sync outcome (ok/result/error/finished_at), or None."""
    row = db.query(AppSetting).filter(AppSetting.key == _LAST_SYNC_KEY).first()
    if not row or not row.value:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def sync_all(db: Session) -> dict:
    _sync_state.update(running=True, started_at=datetime.now().isoformat(),
                       finished_at=None, result=None, error=None)
    error = None
    try:
        result: dict = {}
        errors: dict = {}
        for name, fn in (("senate", sync_senate_trades), ("house", sync_house_trades)):
            try:
                result[name] = fn(db)
                source_health.record(db, name, ok=True, new_rows=result[name])
            except Exception as exc:  # one source failing must not block the other
                result[name] = 0
                errors[name] = str(exc)
                source_health.record(db, name, ok=False, error=str(exc))
        if errors:
            result["errors"] = errors
            error = "; ".join(f"{k}: {v}" for k, v in errors.items())
            _sync_state.update(error=error)
        _sync_state.update(result=result)
        if len(errors) == 2:
            raise RuntimeError(error)
        return result
    except Exception as exc:
        error = error or str(exc)
        _sync_state.update(error=error)
        raise
    finally:
        finished_at = datetime.now().isoformat()
        _sync_state.update(running=False, finished_at=finished_at)
        _persist_last_sync(db, {
            "ok": error is None,
            "finished_at": finished_at,
            "started_at": _sync_state["started_at"],
            "result": _sync_state["result"],
            "error": error,
        })
