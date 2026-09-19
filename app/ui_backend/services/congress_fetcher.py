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
from services import source_health
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
# The owner code (SP spouse / DC dependent child / JT joint; blank = self)
# opens each row, right before the asset name. We look for it at the start of
# the text between the previous transaction and this one.
_HOUSE_OWNER_RE = re.compile(r"^\s*(?:\d+\s+)?(SP|DC|JT)\b")
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


def _trade_exists(db: Session, politician_id: int, ticker: str, trade_date: date,
                  tx_type: str, amount: str) -> bool:
    """Dedup key for a filing row. The amount bracket is part of the key: a
    member can legitimately report two lots of the same ticker on the same
    day, and they differ only by amount."""
    return db.query(Trade.id).filter(
        Trade.politician_id == politician_id,
        Trade.ticker == ticker,
        Trade.trade_date == trade_date,
        Trade.transaction_type == tx_type,
        Trade.amount_range == amount,
    ).first() is not None


def _new_trade(politician_id: int, tx: dict, tx_type: str, trade_date: date,
               disclosure_date: Optional[date], source: str, raw: dict) -> Trade:
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


def _fetch_ptr_list(client: httpx.Client, start_date: date) -> list[dict]:
    """Page through the EFD search API for Senate PTRs filed since `start_date`."""
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
            "submitted_end_date": "",
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


def _fetch_ptr_transactions(client: httpx.Client, uuid: str) -> list[dict]:
    """Fetch one electronic Senate PTR detail page and parse its transactions."""
    resp = _request_with_retry(
        lambda: client.get(f"{EFD_BASE}/search/view/ptr/{uuid}/"),
        label=f"EFD PTR {uuid}",
    )
    return _parse_senate_rows(resp.text)


def sync_senate_trades(db: Session) -> int:
    logger.info("Fetching Senate trades from EFD...")
    start_date = date.today() - timedelta(days=EFD_LOOKBACK_DAYS)

    client = _efd_client()
    seen = _load_processed(db, "senate")
    try:
        reports = _fetch_ptr_list(client, start_date)
        new_reports = [r for r in reports if r["uuid"] not in seen]
        logger.info(f"EFD: {len(reports)} PTRs since {start_date}, {len(new_reports)} new")

        count = 0
        for rpt in new_reports:
                name = f"{rpt['first']} {rpt['last']}".strip()
                if not name:
                    continue
                disclosure_date = _parse_date(rpt["filed"])
                try:
                    txns = _fetch_ptr_transactions(client, rpt["uuid"])
                except Exception as exc:  # one bad filing shouldn't abort the sync
                    logger.warning(f"EFD PTR {rpt['uuid']} failed: {exc}")
                    txns = []
                time.sleep(0.6)  # rate-limit detail-page fetches

                party, state = _enrich(rpt["first"], rpt["last"])
                politician = _get_or_create_politician(db, name, "senate", party=party, state=state)

                for tx in txns:
                    trade_date = _parse_date(tx["transaction_date"])
                    if not trade_date:
                        continue
                    tx_type = tx["type"].lower()
                    if _trade_exists(db, politician.id, tx["ticker"], trade_date, tx_type, tx["amount"]):
                        continue
                    db.add(_new_trade(
                        politician.id, tx, tx_type, trade_date, disclosure_date, "senate",
                        {**tx, "ptr_uuid": rpt["uuid"], "amended": rpt.get("amended", False)},
                    ))
                    db.flush()  # autoflush is off — make this row visible to the next exists-check
                    count += 1
                _mark_processed(db, "senate", rpt["uuid"])
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
        owner_m = _HOUSE_OWNER_RE.match(head)
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
            "owner": sem.normalize_owner(owner_m.group(1) if owner_m else ""),
            "amended": amended,
        })
    return txns


def _parse_house_ptr(pdf_bytes: bytes) -> list[dict]:
    """Extract listed-stock transactions from one electronically-filed PTR PDF."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_house_text(text)


def sync_house_trades(db: Session) -> int:
    """Pull recent House PTRs from the Clerk's office and parse their PDFs.

    Only electronically-filed PTRs (DocID begins with "2") carry a text layer;
    older scanned/handwritten filings are skipped. To keep each sync light we
    look back HOUSE_LOOKBACK_DAYS and skip filings whose PDF we have already
    imported (tracked by DocID in raw_data).
    """
    logger.info("Fetching House trades from Clerk disclosures...")
    cutoff = date.today() - timedelta(days=HOUSE_LOOKBACK_DAYS)
    years = sorted({cutoff.year, date.today().year})

    # DocIDs we've already parsed (incl. filings with no listed-stock trades), so
    # re-syncs don't re-download the same PDFs.
    seen = _load_processed(db, "house")

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

            for row in rows:
                doc_id = (row.get("DocID") or "").strip()
                # FilingType "P" = Periodic Transaction Report; DocID starting
                # with "2" marks an electronic (text-layer) filing.
                if row.get("FilingType") != "P" or not doc_id.startswith("2"):
                    continue
                if doc_id in seen:
                    continue
                filed = _parse_date(row.get("FilingDate"))
                if filed and filed < cutoff:
                    continue

                first, last = (row.get("First") or "").strip(), (row.get("Last") or "").strip()
                name = f"{first} {last}".strip()
                if not name:
                    continue

                try:
                    pdf = client.get(HOUSE_PTR_PDF_URL.format(year=year, doc_id=doc_id))
                    if pdf.status_code != 200:
                        continue  # transient/missing — retry on a later sync
                    txns = _parse_house_ptr(pdf.content)
                except Exception as exc:  # a single bad PDF must not abort the sync
                    logger.warning(f"House PTR {doc_id} failed: {exc}")
                    txns = []
                time.sleep(0.4)  # be polite to a government endpoint

                # State from the filing (e.g. "GA12" → "GA"); party from the roster.
                party, roster_state = _enrich(first, last)
                state = (row.get("StateDst") or "")[:2] or roster_state
                politician = _get_or_create_politician(db, name, "house", party=party, state=state)

                for tx in txns:
                    trade_date = _parse_date(tx["transaction_date"])
                    if not trade_date:
                        continue
                    if _trade_exists(db, politician.id, tx["ticker"], trade_date, tx["type"], tx["amount"]):
                        continue
                    db.add(_new_trade(
                        politician.id, tx, tx["type"], trade_date, _parse_date(tx["disclosure_date"]),
                        "house", {**tx, "ptr_doc_id": doc_id},
                    ))
                    db.flush()  # autoflush is off — make this row visible to the next exists-check
                    count += 1
                seen.add(doc_id)
                _mark_processed(db, "house", doc_id)
                db.commit()
    except Exception as exc:
        logger.error(f"House sync failed: {exc}")
        db.rollback()
        raise
    finally:
        client.close()

    logger.info(f"Synced {count} new House trades")
    return count


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
