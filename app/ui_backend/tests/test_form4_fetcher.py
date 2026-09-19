"""services.form4_fetcher — Form 4 XML parsing and filing selection (no network)."""

from services import form4_fetcher as f4


FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <issuer><issuerCik>0000789019</issuerCik><issuerName>MICROSOFT CORP</issuerName><issuerTradingSymbol>msft</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Nadella Satya</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer><isTenPercentOwner>0</isTenPercentOwner><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-08-12</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1500.5</value></transactionShares>
        <transactionPricePerShare><value>410.25</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-08-12</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1500</value></transactionShares>
        <transactionPricePerShare><value></value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-08-13</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>200</value></transactionShares>
        <transactionPricePerShare><value>400</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


class TestParseForm4Xml:
    def test_metadata(self):
        doc = f4._parse_form4_xml(FORM4_XML)
        assert doc["ticker"] == "MSFT"                    # upper-cased
        assert doc["company_name"] == "MICROSOFT CORP"
        assert doc["insider_name"] == "Nadella Satya"
        assert doc["relationship"] == "Officer"           # officer beats director
        assert doc["insider_title"] == "Chief Executive Officer"

    def test_transaction_codes_map_to_types(self):
        txs = f4._parse_form4_xml(FORM4_XML)["transactions"]
        assert [t["transaction_type"] for t in txs] == ["sell", "other", "buy"]
        assert [t["transaction_code"] for t in txs] == ["S", "M", "P"]

    def test_shares_price_value(self):
        sell, exercise, buy = f4._parse_form4_xml(FORM4_XML)["transactions"]
        assert sell["shares"] == 1500 and sell["price"] == 410.25
        assert sell["value"] == int(1500 * 410.25)
        assert exercise["price"] == 0.0 and exercise["value"] == 0   # blank price → 0, not a crash
        assert buy["value"] == 80_000

    def test_relationship_fallbacks(self):
        director_only = FORM4_XML.replace("<isOfficer>1</isOfficer>", "<isOfficer>0</isOfficer>").replace(
            "<officerTitle>Chief Executive Officer</officerTitle>", "<officerTitle></officerTitle>")
        doc = f4._parse_form4_xml(director_only)
        assert doc["relationship"] == "Director" and doc["insider_title"] == "Director"

    def test_not_an_ownership_document(self):
        assert f4._parse_form4_xml("<html><body>404</body></html>") is None

    def test_malformed_xml(self):
        assert f4._parse_form4_xml("<ownershipDocument><issuer>") is None


class TestRecentForm4s:
    def test_filters_to_form_4_and_caps(self, monkeypatch):
        monkeypatch.setattr(f4, "MAX_FILINGS_PER_TICKER", 2)
        subs = {
            "cik": 789019,
            "filings": {"recent": {
                "form": ["10-K", "4", "4", "8-K", "4"],
                "accessionNumber": ["a", "b", "c", "d", "e"],
                "primaryDocument": ["k.htm", "b.xml", "c.xml", "8.htm", "e.xml"],
                "filingDate": ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"],
            }},
        }
        out = f4._recent_form4s(subs)
        assert [o["accession"] for o in out] == ["b", "c"]
        assert out[0] == {"accession": "b", "primary_doc": "b.xml", "filing_date": "2026-02-01", "cik_raw": "789019"}

    def test_empty(self):
        assert f4._recent_form4s({}) == []
