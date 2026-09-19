"""services.edgar_fetcher — 13F InfoTable parsing, name→ticker mapping, quarter math (no network)."""

from datetime import date

import pytest

from services import edgar_fetcher as ef


def _infotable(rows: list[tuple[str, str, int, int]], shr_type: str = "SH") -> str:
    body = "".join(
        f"<infoTable><nameOfIssuer>{name}</nameOfIssuer><cusip>{cusip}</cusip><value>{value}</value>"
        f"<shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>{shr_type}</sshPrnamtType></shrsOrPrnAmt></infoTable>"
        for name, cusip, value, shares in rows
    )
    return f'<?xml version="1.0"?><informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">{body}</informationTable>'


class TestParseInfotable:
    def test_values_in_thousands_are_scaled(self):
        # $150/share × 1,000,000 shares = $150M → reported as 150000 (thousands)
        xml = _infotable([("APPLE INC", "037833100", 150_000, 1_000_000)] * 3)
        holdings = ef._parse_infotable(xml)
        assert holdings[0]["value_usd"] == 150_000_000
        assert holdings[0]["shares"] == 1_000_000

    def test_values_in_dollars_are_kept(self):
        xml = _infotable([("APPLE INC", "037833100", 150_000_000, 1_000_000)] * 3)
        assert ef._parse_infotable(xml)[0]["value_usd"] == 150_000_000

    def test_sorted_by_value_desc_and_skips_zero(self):
        xml = _infotable([("SMALL CO", "1", 10, 1000), ("BIG CO", "2", 1000, 1000), ("EMPTY", "3", 0, 1000)])
        names = [h["company_name"] for h in ef._parse_infotable(xml)]
        assert names == ["BIG CO", "SMALL CO"]

    def test_principal_amount_rows_have_no_share_count(self):
        xml = _infotable([("US TREASURY", "9", 5_000_000, 5_000_000)], shr_type="PRN")
        (h,) = ef._parse_infotable(xml)
        assert h["shares"] == 0

    def test_malformed(self):
        assert ef._parse_infotable("<informationTable><infoTable>") == []


class TestNameNormalisation:
    @pytest.mark.parametrize("raw, expected", [
        ("Apple Inc.", "APPLE"),
        ("BERKSHIRE HATHAWAY INC DEL CL B", "BERKSHIRE HATHAWAY DEL"),
        ("Alphabet Inc. Class C", "ALPHABET"),
        ("Taiwan Semiconductor Mfg Co Ltd ADR", "TAIWAN SEMICONDUCTOR MFG"),
        ("AT&T Inc", "AT T"),
    ])
    def test_normalize(self, raw, expected):
        assert ef._normalize_name(raw) == expected

    def test_lookup_exact_then_override_then_blank(self, monkeypatch):
        ticker_map = {"APPLE": "AAPL"}
        monkeypatch.setattr(ef, "_NAME_OVERRIDES", {"ALPHABET": "GOOGL"})
        assert ef._lookup_ticker("Apple Inc", ticker_map) == "AAPL"
        assert ef._lookup_ticker("Alphabet Inc Class A", ticker_map) == "GOOGL"
        assert ef._lookup_ticker("Unknown Widgets Corp", ticker_map) == ""


class TestFilingSelection:
    def test_latest_13f_picks_first_hr_or_amendment(self):
        subs = {"cik": 1067983, "filings": {"recent": {
            "form": ["8-K", "13F-HR/A", "13F-HR"],
            "accessionNumber": ["0001-24-1", "0001-24-2", "0001-24-3"],
            "reportDate": ["", "2026-06-30", "2026-03-31"],
        }}}
        assert ef._latest_13f(subs) == ("0001242", "2026-06-30", "1067983")

    def test_latest_13f_none(self):
        assert ef._latest_13f({"filings": {"recent": {"form": ["8-K"]}}}) is None

    @pytest.mark.parametrize("d, q", [("2026-06-30", "2026-Q2"), ("2026-12-31T00:00:00", "2026-Q4"), ("garbage", "")])
    def test_quarter(self, d, q):
        assert ef._quarter(d) == q


class TestChangeType:
    def _holder(self, db):
        from models.whale import WhaleHolder
        h = WhaleHolder(name="Test Fund", cik="0000000001", is_tracked=True)
        db.add(h); db.flush()
        return h

    def test_new_increased_decreased_stable(self, db):
        from models.whale import WhalePosition
        h = self._holder(db)
        assert ef._change_type(h.id, "AAPL", 1_000_000, db) == "new"
        db.add(WhalePosition(holder_id=h.id, ticker="AAPL", company_name="Apple", value_usd=1_000_000,
                             filing_date=date(2026, 5, 15), quarter="2026-Q1", change_type="new"))
        db.flush()
        assert ef._change_type(h.id, "AAPL", 1_100_000, db) == "increased"   # +10%
        assert ef._change_type(h.id, "AAPL", 900_000, db) == "decreased"     # -10%
        assert ef._change_type(h.id, "AAPL", 1_030_000, db) == "stable"      # +3%, inside ±5%
