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

from sqlalchemy.orm import Session

from models.fed_official import FedOfficial

logger = logging.getLogger(__name__)

# OGE publishes 278/278-T reports as PDFs behind a request form — there is
# no machine-readable trade feed, so this module only maintains the roster.

# ── Known FOMC / Fed officials roster ─────────────────────────────────────────
# Board of Governors (permanent FOMC voters) + Regional presidents
# Hand-maintained. ROSTER_AS_OF is shown in the UI so readers know how fresh
# it is; bump it whenever the list is checked against federalreserve.gov.
# Anyone no longer serving goes in FORMER_OFFICIALS so seed_officials() can
# deactivate their row instead of leaving a stale entry.
ROSTER_AS_OF = "2026-09-16"

# Left the Board / their bank; kept only so existing rows get is_active=False.
FORMER_OFFICIALS = ["Adriana Kugler"]

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
        "name": "Stephen Miran",
        "title": "Governor, Board of Governors",
        "role": "board",
        "district": None,
        "is_fomc_voter": True,
        "appointed_by": "Trump",
        "term_expires": "2026",
        "party": "R",
        "bio": "Governor since September 2025, filling the seat vacated by Adriana Kugler. Previously Chair of the Council of Economic Advisers.",
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
    for name in FORMER_OFFICIALS:
        row = db.query(FedOfficial).filter(FedOfficial.name == name).first()
        if row and row.is_active:
            row.is_active = False
    db.commit()
    logger.info(f"Fed officials seeded: {added} new")
    return added
