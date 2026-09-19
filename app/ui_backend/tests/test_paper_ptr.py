"""services.paper_ptr — turning a vision-model reading into parser-shaped rows (no model calls)."""

from services import paper_ptr as pp


READING = {
    "filer": "Hon. Ro Khanna", "amendment": False,
    "transactions": [
        {"asset": "Apple Inc", "ticker": None, "owner": "SP", "type": "P", "transaction_date": "4/16/26",
         "notification_date": "5/4/26", "amount": "C", "confidence": 0.9},
        {"asset": "Microsoft Corp", "ticker": "(MSFT)", "owner": "", "type": "S (partial)", "transaction_date": "04/20/2026",
         "notification_date": None, "amount": "A", "confidence": 0.8},
        {"asset": "Some Private Fund LP", "ticker": None, "owner": "JT", "type": "P", "transaction_date": "4/1/26",
         "notification_date": None, "amount": "B", "confidence": 0.9},          # no ticker → dropped
        {"asset": "Tesla", "ticker": "TSLA", "owner": "", "type": "P", "transaction_date": "??",
         "notification_date": None, "amount": "A", "confidence": 0.9},          # no date → dropped
        {"asset": "Nvidia", "ticker": "NVDA", "owner": "", "type": "P", "transaction_date": "4/2/26",
         "notification_date": None, "amount": None, "confidence": 0.9},         # no amount → dropped
        {"asset": "Ford", "ticker": "F", "owner": "", "type": "S", "transaction_date": "4/3/26",
         "notification_date": None, "amount": "A", "confidence": 0.2},          # low confidence → dropped
    ],
}
LOOKUP = {"APPLE": "AAPL"}.get


def _lookup(name):
    from services.edgar_fetcher import _normalize_name
    return LOOKUP(_normalize_name(name)) or ""


class TestRowsFromReading:
    def test_shapes_and_filters(self):
        rows, stats = pp.rows_from_reading(READING, _lookup)
        assert stats == {"rows": 6, "kept": 2, "no_ticker": 1, "no_date": 1, "no_amount": 1, "low_confidence": 1}
        aapl, msft = rows
        assert aapl["ticker"] == "AAPL" and aapl["owner"] == "SP" and aapl["type"] == "purchase"
        assert aapl["transaction_date"] == "04/16/2026" and aapl["disclosure_date"] == "05/04/2026"
        assert aapl["amount"] == "$50,001 - $100,000" and aapl["ai_confidence"] == 0.9
        assert msft["ticker"] == "MSFT" and msft["type"] == "sale_partial"
        assert msft["disclosure_date"] == "04/20/2026"        # falls back to the transaction date
        assert msft["amount"] == "$1,001 - $15,000"

    def test_amendment_flag(self):
        rows, _ = pp.rows_from_reading({**READING, "amendment": True}, _lookup)
        assert all(r["amended"] for r in rows)


class TestHelpers:
    def test_year4(self):
        assert pp._year4("4/16/26") == "04/16/2026"
        assert pp._year4("04/16/2026") == "04/16/2026"
        assert pp._year4("2026-04-16") is None and pp._year4(None) is None

    def test_parse_json_tolerates_fences_and_prose(self):
        assert pp._parse_json('```json\n{"a": 1}\n```') == {"a": 1}
        assert pp._parse_json('Here you go: {"a": 1} hope it helps') == {"a": 1}
        assert pp._parse_json("nope") is None
