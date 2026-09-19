"""
Shared semantics for congressional trade rows.

Filings describe a transaction with free-ish text (type, owner, asset type,
amount range). Everything downstream — signals, analysis, alerts, the
simulator — needs the same three answers: who owns it, what kind of asset it
is, and whether the trade is a bet *for* or *against* the ticker. Those are
computed once here, stored on the Trade row, and never re-derived from
strings elsewhere.
"""

import re
from typing import Optional

# ── Owner ─────────────────────────────────────────────────────────────────────
# House PTR rows lead with a code; Senate EFD uses words. Empty means self.
OWNER_SELF, OWNER_SPOUSE, OWNER_CHILD, OWNER_JOINT = "self", "spouse", "child", "joint"
_OWNER_MAP = {
    "": OWNER_SELF, "self": OWNER_SELF,
    "sp": OWNER_SPOUSE, "spouse": OWNER_SPOUSE,
    "dc": OWNER_CHILD, "child": OWNER_CHILD, "dependent child": OWNER_CHILD,
    "jt": OWNER_JOINT, "joint": OWNER_JOINT,
}


def normalize_owner(raw: Optional[str]) -> str:
    return _OWNER_MAP.get((raw or "").strip().lower(), OWNER_SELF)


# ── Asset type ────────────────────────────────────────────────────────────────
ASSET_STOCK, ASSET_OPTION, ASSET_OTHER = "stock", "option", "other"


def normalize_asset_type(raw: Optional[str]) -> str:
    """House gives a code ("ST"/"OP"); Senate gives a label ("Stock",
    "Stock Option", "Corporate Bond", ...). Listed stock and ETFs are `stock`;
    anything with a ticker that isn't equity or an option is `other`."""
    v = (raw or "").strip().lower()
    if v in ("", "st", "stock", "exchange traded fund", "etf", "exchange traded funds"):
        return ASSET_STOCK
    if v in ("op", "option") or "option" in v:
        return ASSET_OPTION
    return ASSET_OTHER


# ── Direction ─────────────────────────────────────────────────────────────────
DIR_BUY, DIR_SELL = "buy", "sell"


def direction(transaction_type: Optional[str], asset_type: Optional[str],
              asset_name: Optional[str] = "") -> Optional[str]:
    """Is this trade a bet for (`buy`) or against (`sell`) the ticker?

    * stock: purchase → buy, sale → sell, exchange → None.
    * option: the side depends on the contract. Buying a call or writing a put
      is bullish; buying a put or writing a call is bearish. If the filing
      doesn't say call/put we cannot tell — None keeps it out of the score
      instead of guessing.
    * other (bonds, notes, ...): None — not a view on the equity.
    """
    tx = (transaction_type or "").lower()
    is_buy = "purchase" in tx or tx == "buy"
    is_sell = "sale" in tx or tx == "sell"
    if not (is_buy or is_sell):
        return None
    kind = asset_type or ASSET_STOCK
    if kind == ASSET_STOCK:
        return DIR_BUY if is_buy else DIR_SELL
    if kind == ASSET_OPTION:
        name = (asset_name or "").lower()
        is_call = re.search(r"\bcalls?\b", name) is not None
        is_put = re.search(r"\bputs?\b", name) is not None
        if is_call == is_put:  # neither or both — unknown contract
            return None
        bullish = (is_call and is_buy) or (is_put and is_sell)
        return DIR_BUY if bullish else DIR_SELL
    return None


# ── Amount ────────────────────────────────────────────────────────────────────
_NUM_RE = re.compile(r"\$?\s*([\d,]+)")


def parse_amount_range(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """'$15,001 - $50,000' → (15001, 50000). '$50,000,000 +' → (50000000, None).
    A single figure is treated as both bounds. Returns (None, None) when the
    string has no numbers at all."""
    nums = [int(n.replace(",", "")) for n in _NUM_RE.findall(raw or "") if n.replace(",", "")]
    if not nums:
        return None, None
    if len(nums) == 1:
        open_ended = "+" in (raw or "") or "over" in (raw or "").lower()
        return nums[0], (None if open_ended else nums[0])
    return nums[0], nums[1]


def amount_midpoint(low: Optional[int], high: Optional[int]) -> Optional[int]:
    if low is None:
        return None
    return low if high is None else (low + high) // 2
