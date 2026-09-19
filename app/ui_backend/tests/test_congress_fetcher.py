"""
Unit tests for the congressional disclosure parsers in
services/congress_fetcher.py.

These exercise the pure parsing cores (no network, no DB) using fixtures shaped
like the real government data:

  * House  — text extracted from a Clerk PTR PDF, where rows wrap across lines,
             the two dates print with no separator ("04/16/202605/04/2026"), and
             only "[ST]" listed-stock rows carry a usable ticker.
  * Senate — the EFD detail-page HTML table, whose "Asset Type" column ("Stock")
             sits right next to the "Type" column (Purchase/Sale) we actually
             want — a trap, since "type" is a substring of both.
"""

import pytest

from services.congress_fetcher import (
    _parse_date,
    _norm_name,
    _parse_house_text,
    _parse_senate_rows,
    _request_with_retry,
)


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate:
    def test_us_slash_format(self):
        d = _parse_date("04/16/2026")
        assert (d.year, d.month, d.day) == (2026, 4, 16)

    def test_iso_format(self):
        assert _parse_date("2026-04-16").month == 4

    def test_iso_datetime_format(self):
        assert _parse_date("2026-04-16T00:00:00").day == 16

    def test_whitespace_trimmed(self):
        assert _parse_date("  04/16/2026  ") is not None

    def test_none_and_empty(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None

    def test_unparseable(self):
        assert _parse_date("not a date") is None


# ── _norm_name ────────────────────────────────────────────────────────────────

class TestNormName:
    def test_basic(self):
        assert _norm_name("Nancy", "Pelosi") == "nancy pelosi"

    def test_drops_honorific_and_middle_initial(self):
        # "Hon. Richard W. Allen" should collapse to the roster's "Richard Allen"
        assert _norm_name("Hon. Richard W.", "Allen") == "richard allen"

    def test_strips_punctuation(self):
        assert _norm_name("Thomas H.", "Kean Jr") == "thomas kean"

    def test_empty(self):
        assert _norm_name("", "") == ""


# ── _parse_house_text ─────────────────────────────────────────────────────────

class TestParseHouseText:
    # Real-shaped snippet: dates concatenated, amount straddling the dash.
    SALE = "Abbott Laboratories Common Stock (ABT) [ST]S 04/16/202605/04/2026$15,001 - $50,000"
    PURCHASE = "Intuit Inc. - Common Stock (INTU) [ST] P 05/11/202605/12/2026$1,001 - $15,000"
    EXCHANGE = "Exxon Mobil (XOM) [ST] E 03/01/202603/05/2026$15,001 - $50,000"

    def test_sale(self):
        (tx,) = _parse_house_text(self.SALE)
        assert tx == {
            "ticker": "ABT",
            "type": "sale",
            "transaction_date": "04/16/2026",
            "disclosure_date": "05/04/2026",
            "amount": "$15,001 - $50,000",
            "asset_type": "stock",
            "asset_name": "",
            "owner": "self",
            "amended": False,
        }

    def test_purchase_type_mapping(self):
        (tx,) = _parse_house_text(self.PURCHASE)
        assert tx["type"] == "purchase"
        assert tx["ticker"] == "INTU"

    def test_exchange_type_mapping(self):
        (tx,) = _parse_house_text(self.EXCHANGE)
        assert tx["type"] == "exchange"

    def test_multiple_transactions(self):
        txns = _parse_house_text(self.SALE + "\n" + self.PURCHASE + "\n" + self.EXCHANGE)
        assert [t["ticker"] for t in txns] == ["ABT", "INTU", "XOM"]

    def test_wrapped_across_lines(self):
        # pypdf often splits the asset and the transaction onto separate lines.
        wrapped = "Procter & Gamble Company (PG) [ST]\nS 04/16/202605/04/2026$15,001 -\n$50,000"
        (tx,) = _parse_house_text(wrapped)
        assert tx["ticker"] == "PG" and tx["amount"] == "$15,001 - $50,000"

    def test_dotted_ticker(self):
        (tx,) = _parse_house_text("Berkshire Hathaway (BRK.B) [ST] P 01/02/202601/03/2026$1,001 - $15,000")
        assert tx["ticker"] == "BRK.B"

    def test_skips_government_security(self):
        # Bonds carry "[GS]" and a CUSIP, not a ticker — must be ignored.
        bond = "US Treasury Note 3.75% DUE 12/31/28 (91282CJR3) [GS] S 04/16/202605/04/2026$100,001 - $250,000"
        assert _parse_house_text(bond) == []

    def test_skips_hedge_fund(self):
        # Private funds carry "[HN]" and have no ticker in parentheses.
        fund = "Listen Ventures IV, LP [HN] P 05/13/202605/13/2026$250,001 - $500,000"
        assert _parse_house_text(fund) == []

    def test_captures_option_with_underlying_ticker(self):
        # Options carry "[OP]" and name the underlying in the same "(TICKER)" form.
        opt = "Microsoft Corporation - Common Stock (MSFT) [OP] P 03/25/202604/07/2026$50,001 - $100,000"
        (tx,) = _parse_house_text(opt)
        assert tx["ticker"] == "MSFT"
        assert tx["type"] == "purchase"
        assert tx["asset_type"] == "option"
        assert tx["asset_name"] == "MSFT (option)"

    def test_option_call_put_from_description(self):
        # Real PTRs describe the contract after the amount line.
        text = (
            "SP Microsoft Corporation - Common Stock (MSFT) [OP] P 03/25/202604/07/2026$50,001 - $100,000 "
            "D: Purchased 50 call options with a strike price of $400 and an expiration date of 1/17/2027. "
            "Nvidia Corporation (NVDA) [OP] P 03/25/202604/07/2026$15,001 - $50,000 "
            "D: Purchased 20 put options with a strike price of $100."
        )
        msft, nvda = _parse_house_text(text)
        assert msft["asset_name"] == "MSFT call option" and msft["owner"] == "spouse"
        assert nvda["asset_name"] == "NVDA put option" and nvda["owner"] == "self"

    def test_owner_codes(self):
        text = (
            "1 DC Apple Inc. (AAPL) [ST] P 01/02/202601/03/2026$1,001 - $15,000 "
            "JT Tesla Inc. (TSLA) [ST] S 01/02/202601/03/2026$1,001 - $15,000 "
            "Ford Motor (F) [ST] S 01/02/202601/03/2026$1,001 - $15,000"
        )
        owners = [t["owner"] for t in _parse_house_text(text)]
        assert owners == ["child", "joint", "self"]

    def test_amendment_flagged(self):
        text = "Periodic Transaction Report Amendment\n" + self.SALE
        (tx,) = _parse_house_text(text)
        assert tx["amended"] is True

    def test_not_amended_by_default(self):
        (tx,) = _parse_house_text(self.SALE)
        assert tx["amended"] is False

    def test_empty_text(self):
        assert _parse_house_text("") == []
        assert _parse_house_text("no transactions here") == []


# ── _parse_senate_rows ────────────────────────────────────────────────────────

def _senate_table(rows_html: str, header: str | None = None) -> str:
    default_header = (
        "<th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th>"
        "<th>Asset Name</th><th>Asset Type</th><th>Type</th><th>Amount</th><th>Comment</th>"
    )
    return (
        "<table><thead><tr>"
        + (header or default_header)
        + "</tr></thead><tbody>"
        + rows_html
        + "</tbody></table>"
    )


class TestParseSenateRows:
    def test_picks_type_not_asset_type(self):
        # The regression that bit us: "Asset Type" = Stock, "Type" = Sale.
        html = _senate_table(
            "<tr><td>1</td><td>05/27/2026</td><td>Joint</td><td>VEA</td>"
            "<td>Vanguard Developed Markets</td><td>Stock</td>"
            "<td>Sale (Partial)</td><td>$1,001 - $15,000</td><td>--</td></tr>"
        )
        (tx,) = _parse_senate_rows(html)
        assert tx["type"] == "Sale (Partial)"   # not "Stock"
        assert tx["ticker"] == "VEA"
        assert tx["transaction_date"] == "05/27/2026"
        assert tx["amount"] == "$1,001 - $15,000"
        assert tx["owner"] == "joint"
        assert tx["asset_type"] == "stock"

    def test_senate_option_and_spouse(self):
        html = _senate_table(
            "<tr><td>1</td><td>05/27/2026</td><td>Spouse</td><td>NVDA</td>"
            "<td>NVIDIA Corp call option</td><td>Stock Option</td>"
            "<td>Purchase</td><td>$50,001 - $100,000</td><td>--</td></tr>"
        )
        (tx,) = _parse_senate_rows(html)
        assert tx["owner"] == "spouse" and tx["asset_type"] == "option"

    def test_purchase_row(self):
        html = _senate_table(
            "<tr><td>2</td><td>05/13/2026</td><td>Self</td><td>AAPL</td>"
            "<td>Apple Inc</td><td>Stock</td><td>Purchase</td>"
            "<td>$15,001 - $50,000</td><td>--</td></tr>"
        )
        (tx,) = _parse_senate_rows(html)
        assert tx["ticker"] == "AAPL" and tx["type"] == "Purchase"

    def test_skips_rows_without_ticker(self):
        # A bond row shows "--" in the Ticker column and must be dropped.
        html = _senate_table(
            "<tr><td>1</td><td>05/27/2026</td><td>Self</td><td>AAPL</td>"
            "<td>Apple</td><td>Stock</td><td>Purchase</td><td>$1,001 - $15,000</td><td>--</td></tr>"
            "<tr><td>2</td><td>05/13/2026</td><td>Self</td><td>--</td>"
            "<td>US Treasury</td><td>Corporate Bond</td><td>Purchase</td><td>$50,001 - $100,000</td><td>--</td></tr>"
        )
        txns = _parse_senate_rows(html)
        assert [t["ticker"] for t in txns] == ["AAPL"]

    def test_robust_to_column_reorder(self):
        # Headers in a different order — parsing keys off labels, not position.
        header = (
            "<th>Type</th><th>Ticker</th><th>Transaction Date</th>"
            "<th>Asset Type</th><th>Asset Name</th><th>Amount</th>"
        )
        html = _senate_table(
            "<tr><td>Sale (Full)</td><td>MSFT</td><td>04/01/2026</td>"
            "<td>Stock</td><td>Microsoft</td><td>$1,001 - $15,000</td></tr>",
            header=header,
        )
        (tx,) = _parse_senate_rows(html)
        assert tx["ticker"] == "MSFT"
        assert tx["type"] == "Sale (Full)"
        assert tx["transaction_date"] == "04/01/2026"

    def test_no_table(self):
        assert _parse_senate_rows("<p>No transactions reported.</p>") == []


# ── _request_with_retry ───────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.request = None
    def raise_for_status(self):
        pass


class TestRequestWithRetry:
    def test_returns_on_success(self):
        resp = _request_with_retry(lambda: _FakeResp(200), retries=3, backoff=0)
        assert resp.status_code == 200

    def test_retries_then_succeeds(self):
        calls = {"n": 0}
        def flaky():
            calls["n"] += 1
            return _FakeResp(503 if calls["n"] < 3 else 200)
        resp = _request_with_retry(flaky, retries=3, backoff=0)
        assert resp.status_code == 200 and calls["n"] == 3

    def test_raises_after_exhausting_retries(self):
        with pytest.raises(Exception):
            _request_with_retry(lambda: _FakeResp(429), retries=2, backoff=0)


# ── last-sync persistence (DB round-trip) ─────────────────────────────────────

class TestLastSyncPersistence:
    def test_persist_and_read_back(self, db):
        from services.congress_fetcher import _persist_last_sync, get_last_sync
        assert get_last_sync(db) is None
        payload = {"ok": True, "finished_at": "2026-06-21T00:00:00",
                   "started_at": "2026-06-21T00:00:00", "result": {"house": 5, "senate": 2}, "error": None}
        _persist_last_sync(db, payload)
        got = get_last_sync(db)
        assert got["ok"] is True and got["result"] == {"house": 5, "senate": 2}

    def test_persist_overwrites_previous(self, db):
        from services.congress_fetcher import _persist_last_sync, get_last_sync
        _persist_last_sync(db, {"ok": False, "error": "boom"})
        _persist_last_sync(db, {"ok": True, "error": None})
        assert get_last_sync(db)["ok"] is True
