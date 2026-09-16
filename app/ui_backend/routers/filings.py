"""
Institutional 13F filings via SEC EDGAR public API.
No API key required — SEC mandates public access.

Rate-limit note: SEC asks for ≤10 req/sec, User-Agent required.
Results are cached 6 hours since 13F data is quarterly.
"""

import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from routers.access import require_admin
from sqlalchemy.orm import Session

from database import get_db
from models.filing_institution import FilingInstitution

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/filings", tags=["filings"])

EDGAR_HEADERS = {"User-Agent": "InsiderTrack research@insidertrack.local"}
CACHE_TTL = 21_600  # 6 hours
_cache: dict[str, tuple[float, any]] = {}

# Seed data — used to populate an empty DB on first startup
_DEFAULT_INSTITUTIONS = {
    "Berkshire Hathaway":       "0001067983",
    "BlackRock Advisors":       "0001364742",
    "Vanguard Group":           "0000102909",
    "State Street":             "0000093751",
    "JPMorgan Chase":           "0000019617",
    "Goldman Sachs Group":      "0000886982",
    "Citadel Advisors":         "0001423298",
    "Millennium Management":    "0001273931",
    "Renaissance Technologies": "0001037389",
    "Bridgewater Associates":   "0001350694",
}


def seed_filing_institutions(db: Session) -> int:
    """Populate filing_institutions from defaults if the table is empty."""
    if db.query(FilingInstitution).count() > 0:
        return 0
    added = 0
    for name, cik in _DEFAULT_INSTITUTIONS.items():
        db.add(FilingInstitution(name=name, cik=cik))
        added += 1
    db.commit()
    return added


def _cache_get(key):
    e = _cache.get(key)
    return e[1] if e and (time.time() - e[0]) < CACHE_TTL else None


def _cache_set(key, data):
    _cache[key] = (time.time(), data)


def _fetch_submissions(cik: str) -> dict | None:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    cached = _cache_get(url)
    if cached is not None:
        return cached
    try:
        with httpx.Client(timeout=15, headers=EDGAR_HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
            _cache_set(url, data)
            return data
    except Exception as e:
        logger.warning(f"EDGAR submissions fetch failed for CIK {cik}: {e}")
        return None


def _extract_13f_filings(submissions: dict, limit: int = 5) -> list[dict]:
    """Pull the N most recent 13F-HR filings from a submissions response."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    periods = recent.get("reportDate", [])
    accessions = recent.get("accessionNumber", [])

    results = []
    for i, form in enumerate(forms):
        if form not in ("13F-HR", "13F-HR/A"):
            continue
        acc = accessions[i] if i < len(accessions) else ""
        acc_clean = acc.replace("-", "")
        cik_raw = submissions.get("cik", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_clean}/"
            if acc_clean else ""
        )
        index_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik_raw}&type=13F-HR&dateb=&owner=include&count=10"
        )
        results.append({
            "form": form,
            "filing_date": dates[i] if i < len(dates) else "",
            "period": periods[i] if i < len(periods) else "",
            "accession": acc,
            "filing_url": filing_url,
            "index_url": index_url,
        })
        if len(results) >= limit:
            break
    return results


# ── Pydantic ──────────────────────────────────────────────────────────────────

class InstitutionCreate(BaseModel):
    name: str
    cik: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/institutions")
def list_institutions(db: Session = Depends(get_db)):
    """List the tracked institutional filers."""
    rows = db.query(FilingInstitution).order_by(FilingInstitution.name).all()
    return [{"name": r.name, "cik": r.cik} for r in rows]


@router.post("/institutions", status_code=201)
def add_institution(body: InstitutionCreate, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Add a new institution to track."""
    cik = body.cik.strip().zfill(10)
    existing = db.query(FilingInstitution).filter(FilingInstitution.cik == cik).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"CIK {cik} already tracked as '{existing.name}'")
    row = FilingInstitution(name=body.name.strip(), cik=cik)
    db.add(row)
    db.commit()
    return {"name": row.name, "cik": row.cik}


@router.delete("/institutions/{cik}", status_code=204)
def delete_institution(cik: str, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    """Remove an institution from tracking."""
    padded = cik.strip().zfill(10)
    row = db.query(FilingInstitution).filter(FilingInstitution.cik == padded).first()
    if not row:
        raise HTTPException(status_code=404, detail="Institution not found")
    db.delete(row)
    db.commit()


@router.get("/recent")
def recent_filings(limit_per: int = 3, db: Session = Depends(get_db)):
    """Fetch recent 13F-HR filings for each tracked institution from SEC EDGAR."""
    institutions = db.query(FilingInstitution).order_by(FilingInstitution.name).all()
    results = []
    for inst in institutions:
        subs = _fetch_submissions(inst.cik)
        if not subs:
            results.append({"institution": inst.name, "cik": inst.cik, "filings": [], "error": "Could not fetch from SEC EDGAR"})
            continue
        filings = _extract_13f_filings(subs, limit=limit_per)
        entity_name = subs.get("name", inst.name)
        results.append({
            "institution": entity_name or inst.name,
            "cik": inst.cik,
            "sic_description": subs.get("sicDescription", ""),
            "filings": filings,
        })
    return results


@router.get("/{cik}")
def institution_filings(cik: str, limit: int = 10):
    """All recent 13F-HR filings for a specific institution by CIK."""
    padded = cik.zfill(10)
    subs = _fetch_submissions(padded)
    if not subs:
        raise HTTPException(status_code=502, detail="Could not fetch from SEC EDGAR")
    filings = _extract_13f_filings(subs, limit=limit)
    return {
        "institution": subs.get("name", ""),
        "cik": padded,
        "filings": filings,
    }
