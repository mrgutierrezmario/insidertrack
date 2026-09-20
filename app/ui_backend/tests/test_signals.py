"""
Unit tests for signal scoring math in routers/signals.py.
No database or external API calls required.
"""

import pytest
from routers.signals import (
    _sma,
    _rsi,
    _momentum_score,
    _insider_score,
    _corporate_score,
    _composite_label,
    _bullish_label,
    _smart_money_from_positions,
    _risk_penalty_from_trades,
)


# ── _sma ──────────────────────────────────────────────────────────────────────

class TestSma:
    def test_exact_period(self):
        assert _sma([1, 2, 3, 4, 5], 5) == 3.0

    def test_uses_last_n_bars(self):
        # SMA(3) of [1,2,3,4,5] should use [3,4,5] → 4.0
        assert _sma([1, 2, 3, 4, 5], 3) == 4.0

    def test_insufficient_data_returns_none(self):
        assert _sma([1, 2], 5) is None

    def test_single_value(self):
        assert _sma([42.0], 1) == 42.0


# ── _rsi ──────────────────────────────────────────────────────────────────────

class TestRsi:
    def test_insufficient_data_returns_none(self):
        assert _rsi([1, 2, 3], period=14) is None

    def test_all_gains_returns_near_100(self):
        prices = list(range(1, 20))   # strictly increasing
        result = _rsi(prices, period=14)
        assert result is not None
        assert result > 90

    def test_all_losses_returns_near_0(self):
        prices = list(range(20, 0, -1))  # strictly decreasing
        result = _rsi(prices, period=14)
        assert result is not None
        assert result < 10

    def test_neutral_returns_around_50(self):
        # Alternating +1/-1 moves → roughly neutral RSI
        prices = [100 + (1 if i % 2 == 0 else -1) for i in range(20)]
        result = _rsi(prices, period=14)
        assert result is not None
        assert 30 < result < 70

    def test_result_bounded_0_to_100(self):
        prices = [float(i) for i in range(1, 30)]
        result = _rsi(prices)
        assert result is not None
        assert 0 <= result <= 100


# ── _momentum_score ───────────────────────────────────────────────────────────

class TestMomentumScore:
    def test_no_data_returns_neutral(self):
        score, reasons = _momentum_score([])
        assert score == 12
        assert reasons

    def test_score_bounded(self):
        prices = [float(i) for i in range(1, 65)]
        score, _ = _momentum_score(prices)
        assert 0 <= score <= 25

    def test_bullish_trend_above_neutral(self):
        # Rising prices → SMA20 > SMA50 likely, price above SMA20
        prices = [float(i) for i in range(1, 65)]
        score, _ = _momentum_score(prices)
        assert score > 12

    def test_bearish_trend_below_neutral(self):
        # Falling prices
        prices = [float(65 - i) for i in range(65)]
        score, _ = _momentum_score(prices)
        assert score < 12

    def test_reasons_non_empty(self):
        prices = [float(i) for i in range(1, 65)]
        _, reasons = _momentum_score(prices)
        assert len(reasons) > 0


# ── _insider_score ────────────────────────────────────────────────────────────

class TestInsiderScore:
    def test_no_activity_neutral(self):
        score, _ = _insider_score(0, 0)
        assert score == 15

    def test_all_buys_max(self):
        score, _ = _insider_score(5, 0)
        assert score == 30

    def test_all_sells_min(self):
        score, _ = _insider_score(0, 5)
        assert score == 0

    def test_majority_buys_high_score(self):
        score, _ = _insider_score(7, 3)
        assert score >= 20

    def test_majority_sells_low_score(self):
        score, _ = _insider_score(2, 8)
        assert score <= 7

    def test_mixed_returns_middle(self):
        score, _ = _insider_score(5, 5)
        assert 7 <= score <= 24


class TestInsiderScoreDollarWeighted:
    def test_dollars_beat_counts(self):
        # Five $8K buys vs one $5M sale: by count that's "bullish lean",
        # by dollars it's overwhelmingly a sell.
        score, reasons = _insider_score(5, 1, buy_dollars=40_000, sell_dollars=5_000_000)
        assert score == 7
        assert "$5.0M" in reasons[0]

    def test_all_buys_with_dollars(self):
        score, reasons = _insider_score(2, 0, buy_dollars=100_000, sell_dollars=0)
        assert score == 30 and "$100K" in reasons[0]

    def test_falls_back_to_counts_without_dollars(self):
        assert _insider_score(7, 3)[0] == 24


# ── _corporate_score ──────────────────────────────────────────────────────────

class _F4:
    def __init__(self, ttype, value, name="A. Insider"):
        self.transaction_type = ttype
        self.value = value
        self.insider_name = name


class TestCorporateScore:
    def test_empty_is_neutral(self):
        score, reasons = _corporate_score([])
        assert score == 12 and "No Form 4" in reasons[0]

    def test_all_buys(self):
        score, _ = _corporate_score([_F4("buy", 250_000)])
        assert score == 22

    def test_cluster_buy_bonus_caps_at_20(self):
        txns = [_F4("buy", 100_000, "CEO"), _F4("buy", 50_000, "CFO"), _F4("buy", 10_000, "Director")]
        score, reasons = _corporate_score(txns)
        assert score == 25
        assert any("Cluster buy: 3" in r for r in reasons)

    def test_all_sells_is_discounted_not_zero(self):
        score, reasons = _corporate_score([_F4("sell", 1_000_000)])
        assert score == 4 and "routine" in reasons[0]

    def test_dollar_weighted_ratio(self):
        # one big buy vs many tiny sells → net buyers
        txns = [_F4("buy", 900_000)] + [_F4("sell", 10_000, f"s{i}") for i in range(5)]
        score, _ = _corporate_score(txns)
        assert score == 18

    def test_grants_only_are_neutral(self):
        score, reasons = _corporate_score([_F4("other", 0)])
        assert score == 12 and "grants" in reasons[0]


# ── _composite_label ─────────────────────────────────────────────────────────

class TestCompositeLabel:
    @pytest.mark.parametrize("score,expected", [
        (100, "Strong Watch"),
        (70,  "Strong Watch"),
        (69,  "Watch"),
        (50,  "Watch"),
        (49,  "Neutral"),
        (30,  "Neutral"),
        (29,  "High Risk"),
        (15,  "High Risk"),
        (14,  "Avoid for Now"),
        (0,   "Avoid for Now"),
    ])
    def test_boundaries(self, score, expected):
        assert _composite_label(score) == expected


# ── _bullish_label ────────────────────────────────────────────────────────────

class TestBullishLabel:
    @pytest.mark.parametrize("score,expected", [
        (3,   "BULLISH"),
        (2,   "BULLISH"),
        (1,   "NEUTRAL"),
        (0,   "NEUTRAL"),
        (-1,  "NEUTRAL"),
        (-2,  "BEARISH"),
        (-3,  "BEARISH"),
    ])
    def test_thresholds(self, score, expected):
        assert _bullish_label(score) == expected


# ── _smart_money_from_positions ───────────────────────────────────────────────

class TestSmartMoneyFromPositions:
    def _make_pos(self, change_type, holder_name="BlackRock", value=1_000_000, holder_id=1, quarter="2026-Q2"):
        class FakeHolder:
            name = holder_name
        class FakePos:
            def __init__(self):
                self.change_type = change_type
                self.holder = FakeHolder()
                self.holder_id = holder_id
                self.quarter = quarter
                self.value_usd = value
        return FakePos()

    def test_initial_quarter_is_neutral(self):
        score, _ = _smart_money_from_positions([self._make_pos("initial")])
        assert score == 10

    def test_conviction_weights_and_bonus(self):
        # 10% of a $100M book that was increased → weighted up + high-conviction bonus (capped 20)
        totals = {(1, "2026-Q2"): 100_000_000}
        score, reasons = _smart_money_from_positions([self._make_pos("increased", value=10_000_000)], totals)
        assert score == 18 and any("High conviction: 10%" in r for r in reasons)
        # the same change at 0.1% of the book is just the plain change score
        score2, _ = _smart_money_from_positions([self._make_pos("increased", value=100_000)], totals)
        assert score2 == 15

    def test_empty_returns_neutral(self):
        score, reasons = _smart_money_from_positions([])
        assert score == 10
        assert "No institutional" in reasons[0]

    def test_new_position_max_score(self):
        pos = [self._make_pos("new")]
        score, _ = _smart_money_from_positions(pos)
        assert score == 20

    def test_closed_position_zero_score(self):
        pos = [self._make_pos("closed")]
        score, _ = _smart_money_from_positions(pos)
        assert score == 0

    def test_mixed_positions_averaged(self):
        positions = [self._make_pos("new"), self._make_pos("closed")]
        score, _ = _smart_money_from_positions(positions)
        assert score == 10  # (20 + 0) / 2

    def test_increased_reason_in_output(self):
        pos = [self._make_pos("increased")]
        _, reasons = _smart_money_from_positions(pos)
        assert any("increased" in r for r in reasons)


# ── _risk_penalty_from_trades ─────────────────────────────────────────────────

class TestRiskPenaltyFromTrades:
    def test_empty_no_penalty(self):
        penalty, reasons = _risk_penalty_from_trades([])
        assert penalty == 0
        assert reasons == []

    def test_high_risk_adds_5_per_trade(self):
        from datetime import date, timedelta
        from models.trade import Trade

        t = Trade()
        t.trade_date = date.today() - timedelta(days=60)   # old → HIGH age risk
        t.disclosure_date = date.today() - timedelta(days=55)
        t.amount_range = "$1,001 - $15,000"

        penalty, reasons = _risk_penalty_from_trades([t])
        assert penalty == 5
        assert any("HIGH" in r for r in reasons)

    def test_penalty_capped_at_20(self):
        from datetime import date, timedelta
        from models.trade import Trade

        trades = []
        for _ in range(10):
            t = Trade()
            t.trade_date = date.today() - timedelta(days=60)
            t.disclosure_date = date.today() - timedelta(days=55)
            t.amount_range = "$1,001 - $15,000"
            trades.append(t)

        penalty, _ = _risk_penalty_from_trades(trades)
        assert penalty == 20
