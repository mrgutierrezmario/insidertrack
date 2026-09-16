"""
Federal Reserve officials financial disclosure fetcher.

Sources (in priority order):
1. OGE EFTS API  — structured JSON for Board of Governors annual 278 reports
2. Individual Fed Bank disclosure pages (HTML scrape for regional presidents)
3. Pre-seeded roster always ensures officials are shown even if trade data unavailable

After the 2021 trading scandal the Fed required 45-day transaction disclosure.
Board of Governors members file with the Office of Government Ethics (OGE).
Regional bank presidents publish disclosures on their own bank websites.
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from models.fed_official import FedOfficial, FedTrade

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "InsiderTrack/1.0 contact@insidertrack.local"}
# Placeholder: OGE publishes 278/278-T reports as PDFs, not a JSON API. This
# host does not exist, so sync_oge_trades() currently fetches nothing.
OGE_API = "https://efts.usethical.com/EOGE/api"

# ── Known FOMC / Fed officials roster ─────────────────────────────────────────
# Board of Governors (permanent FOMC voters) + Regional presidents
# Updated as of 2025. Appointing president's party noted.
FED_OFFICIALS_SEED = [
    # Board of Governors -------------------------------------------------------
    {
        "name": "Jerome Powell",
        "title": "Chair, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Trump / Biden",
        "term_expires": "2026",
        "party": "R",
        "bio": "Chair of the Federal Reserve since 2018. Reappointed by President Biden in 2022. Former private equity attorney and partner at The Carlyle Group. Oversees all monetary policy decisions.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    {
        "name": "Philip Jefferson",
        "title": "Vice Chair, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Biden",
        "term_expires": "2036",
        "party": "D",
        "bio": "Vice Chair since 2023. Former economics professor at Davidson College. Focuses on labor market outcomes and monetary policy transmission.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    {
        "name": "Michelle Bowman",
        "title": "Governor, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Trump",
        "term_expires": "2034",
        "party": "R",
        "bio": "Governor since 2018. Former Kansas State Bank Commissioner. Known for dissenting votes on rate decisions; advocates for lighter regulatory approach.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    {
        "name": "Lisa Cook",
        "title": "Governor, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Biden",
        "term_expires": "2038",
        "party": "D",
        "bio": "Governor since 2022. First Black woman to serve on the Federal Reserve Board. Economics professor at Michigan State University. Research focus on innovation and economic history.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    {
        "name": "Adriana Kugler",
        "title": "Governor, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Biden",
        "term_expires": "2026",
        "party": "D",
        "bio": "Governor since 2023. Former Chief Economist at the U.S. Department of Labor and World Bank. Research expertise in labor markets and immigration economics.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    {
        "name": "Christopher Waller",
        "title": "Governor, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Trump",
        "term_expires": "2030",
        "party": "R",
        "bio": "Governor since 2020. Former Research Director at the Federal Reserve Bank of St. Louis. Macroeconomist known for data-driven policy views and willingness to cut rates when inflation falls.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    {
        "name": "Michael Barr",
        "title": "Governor, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Biden",
        "term_expires": "2032",
        "party": "D",
        "bio": "Governor since 2022. Former Vice Chair for Supervision (resigned that role in 2025). Law professor at University of Michigan. Expert in financial regulation and consumer protection.",
        "disclosure_url": "https://www.federalreserve.gov/aboutthefed/disclosures.htm",
    },
    # Regional Presidents (NY is permanent voter; others rotate annually) ------
    {
        "name": "John Williams",
        "title": "President & CEO, Federal Reserve Bank of New York",
        "role": "regional_president",
        "district": "New York",
        "is_fomc_voter": True,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the NY Fed since 2018. NY Fed president is a permanent FOMC voter and vice chair of the committee. Former president of the San Francisco Fed. Macroeconomist and monetary policy expert.",
        "disclosure_url": "https://www.newyorkfed.org/aboutthefed/ethicsanddisclosures",
    },
    {
        "name": "Austan Goolsbee",
        "title": "President & CEO, Federal Reserve Bank of Chicago",
        "role": "regional_president",
        "district": "Chicago",
        "is_fomc_voter": True,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Chicago Fed since 2023. Former Chair of the Council of Economic Advisers under President Obama. Economics professor at University of Chicago Booth School of Business. Considered a monetary policy dove.",
        "disclosure_url": "https://www.chicagofed.org/people/g/goolsbee-austan",
    },
    {
        "name": "Neel Kashkari",
        "title": "President & CEO, Federal Reserve Bank of Minneapolis",
        "role": "regional_president",
        "district": "Minneapolis",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Minneapolis Fed since 2016. Former head of TARP during the 2008 financial crisis. Known for hawkish stances on inflation and holding rates higher for longer.",
        "disclosure_url": "https://www.minneapolisfed.org/people/kashkari-neel",
    },
    {
        "name": "Raphael Bostic",
        "title": "President & CEO, Federal Reserve Bank of Atlanta",
        "role": "regional_president",
        "district": "Atlanta",
        "is_fomc_voter": True,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Atlanta Fed since 2017. First Black president of a regional Federal Reserve bank. Former HUD Assistant Secretary. Focuses on inclusive growth and community development.",
        "disclosure_url": "https://www.atlantafed.org/people/bostic-raphael",
    },
    {
        "name": "Lorie Logan",
        "title": "President & CEO, Federal Reserve Bank of Dallas",
        "role": "regional_president",
        "district": "Dallas",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Dallas Fed since 2022. Former head of open market operations at the NY Fed. Expert in monetary policy implementation, reserve management, and the Fed's balance sheet.",
        "disclosure_url": "https://www.dallasfed.org/people/l/logan-lorie",
    },
    {
        "name": "Mary Daly",
        "title": "President & CEO, Federal Reserve Bank of San Francisco",
        "role": "regional_president",
        "district": "San Francisco",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the San Francisco Fed since 2018. Former EVP and Director of Research at SF Fed. Labor economist known for data-dependent approach and emphasis on Fed dual mandate.",
        "disclosure_url": "https://www.frbsf.org/people/daly-mary-c/",
    },
    {
        "name": "Susan Collins",
        "title": "President & CEO, Federal Reserve Bank of Boston",
        "role": "regional_president",
        "district": "Boston",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Boston Fed since 2022. Former Provost at University of Michigan. International economist focused on emerging markets and exchange rate policy.",
        "disclosure_url": "https://www.bostonfed.org/people/bank/susan-m-collins.aspx",
    },
    {
        "name": "Patrick Harker",
        "title": "President & CEO, Federal Reserve Bank of Philadelphia",
        "role": "regional_president",
        "district": "Philadelphia",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Philadelphia Fed since 2015. Former President of the University of Delaware. Engineering background; focuses on workforce development and regional economic analysis.",
        "disclosure_url": "https://www.philadelphiafed.org/people/harker-patrick-t",
    },
    {
        "name": "Tom Barkin",
        "title": "President & CEO, Federal Reserve Bank of Richmond",
        "role": "regional_president",
        "district": "Richmond",
        "is_fomc_voter": True,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Richmond Fed since 2018. Former CFO at McKinsey & Company. Focuses on business conditions through extensive outreach; known for business-cycle pragmatism.",
        "disclosure_url": "https://www.richmondfed.org/people/barkin_thomas_i",
    },
    {
        "name": "Alberto Musalem",
        "title": "President & CEO, Federal Reserve Bank of St. Louis",
        "role": "regional_president",
        "district": "St. Louis",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the St. Louis Fed since 2024. Former portfolio manager and macroeconomist at investment firms including Tudor Investment Corp. Focuses on inflation dynamics and financial stability.",
        "disclosure_url": "https://www.stlouisfed.org/people/m/musalem-alberto",
    },
    {
        "name": "Jeffrey Schmid",
        "title": "President & CEO, Federal Reserve Bank of Kansas City",
        "role": "regional_president",
        "district": "Kansas City",
        "is_fomc_voter": False,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Kansas City Fed since 2023. Former CEO of Heartland Financial and Sunflower Bank. Focus on financial services, agricultural economy, and energy sector.",
        "disclosure_url": "https://www.kansascityfed.org/people/jeff-schmid/",
    },
    {
        "name": "Beth Hammack",
        "title": "President & CEO, Federal Reserve Bank of Cleveland",
        "role": "regional_president",
        "district": "Cleveland",
        "is_fomc_voter": True,
        "appointed_by": "Fed Board",
        "term_expires": "N/A",
        "party": None,
        "bio": "President of the Cleveland Fed since 2024. Former Co-head of Global Financing at Goldman Sachs. Expert in fixed income markets, liquidity management, and monetary policy implementation.",
        "disclosure_url": "https://www.clevelandfed.org/people/h/hammack-beth",
    },
]

# Notable historical trades (from 2021 disclosed transactions + OGE filings)
# These are documented public record trades that led to the 2021 scandal
# No seeded trades. Earlier versions shipped a few hard-coded rows attributed to
# sitting governors; they were placeholders, not disclosures, and were removed.
# Board members have been barred from buying individual stocks since the 2022
# investment policy, so an empty table here is the expected state.
FED_TRADES_SEED: list[dict] = []


# ── OGE EFTS API ───────────────────────────────────────────────────────────────

def _oge_search(name: str) -> list[dict]:
    """Search OGE EFTS for filings by a Fed official by name."""
    try:
        with httpx.Client(timeout=15, headers=HEADERS) as client:
            r = client.get(f"{OGE_API}/filing/get_records/", params={
                "searchText": name,
                "filerTypes": "1",   # Executive branch filers
                "agencies": "FRB",   # Federal Reserve Board
                "pageSize": 10,
            })
            r.raise_for_status()
            data = r.json()
            return data.get("results", []) or []
    except Exception as e:
        logger.debug(f"OGE search for {name} failed: {e}")
        return []


def _oge_transactions(filing_id: str) -> list[dict]:
    """Fetch transaction schedule (Part 4) from an OGE filing."""
    try:
        with httpx.Client(timeout=15, headers=HEADERS) as client:
            r = client.get(f"{OGE_API}/filing/{filing_id}/transactions/")
            r.raise_for_status()
            return r.json().get("results", []) or []
    except Exception:
        return []


# ── Seed / sync helpers ────────────────────────────────────────────────────────

def seed_officials(db: Session) -> int:
    """Insert known officials if they don't already exist."""
    added = 0
    for o in FED_OFFICIALS_SEED:
        existing = db.query(FedOfficial).filter(FedOfficial.name == o["name"]).first()
        if existing:
            # Update mutable fields in case data changed
            existing.title = o["title"]
            existing.role = o["role"]
            existing.district = o.get("district")
            existing.is_fomc_voter = o["is_fomc_voter"]
            existing.appointed_by = o.get("appointed_by")
            existing.term_expires = o.get("term_expires")
            existing.party = o.get("party")
            existing.bio = o.get("bio", "")
            existing.disclosure_url = o.get("disclosure_url")
        else:
            db.add(FedOfficial(
                name=o["name"],
                title=o["title"],
                role=o["role"],
                district=o.get("district"),
                is_fomc_voter=o["is_fomc_voter"],
                appointed_by=o.get("appointed_by"),
                term_expires=o.get("term_expires"),
                party=o.get("party"),
                bio=o.get("bio", ""),
                disclosure_url=o.get("disclosure_url"),
                is_active=True,
            ))
            added += 1
    db.commit()
    logger.info(f"Fed officials seeded: {added} new")
    return added


def seed_trades(db: Session) -> int:
    """Insert known seed trades (from disclosed public records)."""
    added = 0
    for t in FED_TRADES_SEED:
        official = db.query(FedOfficial).filter(FedOfficial.name == t["official_name"]).first()
        if not official:
            continue
        td = date.fromisoformat(t["trade_date"])
        existing = db.query(FedTrade).filter(
            FedTrade.official_id == official.id,
            FedTrade.ticker == t["ticker"],
            FedTrade.trade_date == td,
            FedTrade.transaction_type == t["transaction_type"],
        ).first()
        if existing:
            continue
        db.add(FedTrade(
            official_id=official.id,
            ticker=t["ticker"],
            asset_name=t.get("asset_name"),
            transaction_type=t["transaction_type"],
            amount_range=t.get("amount_range"),
            trade_date=td,
            disclosure_date=date.fromisoformat(t["disclosure_date"]) if t.get("disclosure_date") else None,
            filing_year=t.get("filing_year"),
            source=t.get("source", "oge"),
            source_url=t.get("source_url"),
        ))
        added += 1
    db.commit()
    logger.info(f"Fed seed trades inserted: {added}")
    return added


def sync_oge_trades(db: Session) -> dict:
    """
    Try to pull transaction data from OGE EFTS for Board of Governors members.
    Returns counts of what was found.
    """
    board_members = (
        db.query(FedOfficial)
        .filter(FedOfficial.role == "board", FedOfficial.is_active == True)  # noqa: E712
        .all()
    )
    fetched = 0
    stored = 0

    for official in board_members:
        try:
            filings = _oge_search(official.name)
            for filing in filings[:3]:  # only most recent filings
                filing_id = filing.get("id") or filing.get("filing_id")
                if not filing_id:
                    continue
                filing_year = filing.get("year") or filing.get("reportYear")
                transactions = _oge_transactions(str(filing_id))
                fetched += len(transactions)
                for tx in transactions:
                    ticker = (tx.get("ticker") or tx.get("asset_ticker") or "").upper().strip()
                    if not ticker or len(ticker) > 10:
                        continue
                    tx_type_raw = (tx.get("type") or tx.get("transactionType") or "").lower()
                    tx_type = "purchase" if "purchase" in tx_type_raw or "buy" in tx_type_raw else \
                              "sale" if "sale" in tx_type_raw or "sell" in tx_type_raw else "other"
                    td_str = tx.get("date") or tx.get("transactionDate") or tx.get("trade_date")
                    if not td_str:
                        continue
                    try:
                        td = date.fromisoformat(td_str[:10])
                    except ValueError:
                        continue
                    existing = db.query(FedTrade).filter(
                        FedTrade.official_id == official.id,
                        FedTrade.ticker == ticker,
                        FedTrade.trade_date == td,
                        FedTrade.transaction_type == tx_type,
                    ).first()
                    if existing:
                        continue
                    db.add(FedTrade(
                        official_id=official.id,
                        ticker=ticker,
                        asset_name=tx.get("asset_name") or tx.get("assetName") or "",
                        transaction_type=tx_type,
                        amount_range=tx.get("amount") or tx.get("value_range") or "",
                        trade_date=td,
                        filing_year=filing_year,
                        source="oge",
                        source_url=f"https://efts.usethical.com/EOGE/api/filing/{filing_id}/",
                    ))
                    stored += 1
            time.sleep(0.5)  # be polite to OGE API
        except Exception as e:
            logger.warning(f"OGE sync failed for {official.name}: {e}")

    if stored:
        db.commit()
    logger.info(f"OGE sync: {fetched} transactions found, {stored} new stored")
    return {"fetched": fetched, "stored": stored}


def sync_all(db: Session) -> dict:
    """Full sync: seed officials → seed known trades → try OGE live fetch."""
    officials_added = seed_officials(db)
    trades_seeded = seed_trades(db)
    oge_result = sync_oge_trades(db)
    return {
        "officials_added": officials_added,
        "trades_seeded": trades_seeded,
        "oge_fetched": oge_result["fetched"],
        "oge_stored": oge_result["stored"],
    }
