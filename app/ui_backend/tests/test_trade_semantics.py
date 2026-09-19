"""services.trade_semantics — owner/asset/direction/amount normalisation."""

import pytest

from services import trade_semantics as sem


class TestParseAmountRange:
    @pytest.mark.parametrize("raw, expected", [
        ("$1,001 - $15,000", (1001, 15000)),
        ("$15,001 -$50,000", (15001, 50000)),
        ("$50,000,001 - $100,000,000", (50000001, 100000000)),
        ("Over $50,000,000", (50000000, None)),
        ("$50,000,000 +", (50000000, None)),
        ("$1,000", (1000, 1000)),
        ("", (None, None)),
        (None, (None, None)),
        ("--", (None, None)),
    ])
    def test_parse(self, raw, expected):
        assert sem.parse_amount_range(raw) == expected

    def test_midpoint(self):
        assert sem.amount_midpoint(1001, 15000) == 8000
        assert sem.amount_midpoint(50000000, None) == 50000000
        assert sem.amount_midpoint(None, None) is None


class TestNormalize:
    def test_owner(self):
        assert sem.normalize_owner("SP") == "spouse"
        assert sem.normalize_owner("dc") == "child"
        assert sem.normalize_owner("Joint") == "joint"
        assert sem.normalize_owner("Self") == "self"
        assert sem.normalize_owner("") == "self"
        assert sem.normalize_owner(None) == "self"

    def test_asset_type(self):
        assert sem.normalize_asset_type("ST") == "stock"
        assert sem.normalize_asset_type("Stock") == "stock"
        assert sem.normalize_asset_type("Exchange Traded Fund") == "stock"
        assert sem.normalize_asset_type("OP") == "option"
        assert sem.normalize_asset_type("Stock Option") == "option"
        assert sem.normalize_asset_type("Corporate Bond") == "other"
        assert sem.normalize_asset_type("") == "stock"


class TestDirection:
    def test_stock(self):
        assert sem.direction("purchase", "stock") == "buy"
        assert sem.direction("Sale (Partial)".lower(), "stock") == "sell"
        assert sem.direction("sale (full)", "stock") == "sell"
        assert sem.direction("exchange", "stock") is None
        # legacy rows have no asset_type — treat as stock
        assert sem.direction("purchase", None) == "buy"

    def test_options_follow_the_contract(self):
        assert sem.direction("purchase", "option", "MSFT call option") == "buy"
        assert sem.direction("purchase", "option", "MSFT put option") == "sell"
        assert sem.direction("sale", "option", "MSFT call option") == "sell"
        assert sem.direction("sale", "option", "MSFT put option") == "buy"

    def test_unknown_option_contract_is_neutral(self):
        # The regression this exists for: a put purchase must never score as a buy.
        assert sem.direction("purchase", "option", "MSFT (option)") is None
        assert sem.direction("purchase", "option", "") is None

    def test_other_assets_are_neutral(self):
        assert sem.direction("purchase", "other", "US Treasury Note") is None
