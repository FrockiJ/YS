from __future__ import annotations

import re
import zlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


MIN_FAKE_LIST_PRICE = Decimal("80")
VIP_PRICE_RATIO = Decimal("0.85")


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _round_to_nearest_10(value: Decimal) -> Decimal:
    rounded_units = (value / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(rounded_units * Decimal("10"), MIN_FAKE_LIST_PRICE)


def _hash_ratio(seed: str) -> Decimal:
    normalized = str(seed or "").strip().upper()
    if not normalized:
        return Decimal("0")
    value = zlib.crc32(normalized.encode("utf-8")) % 10000
    return Decimal(value) / Decimal("9999")


def _price_band(name: str, spec1: str) -> tuple[Decimal, Decimal]:
    haystack = f"{name} {spec1}".casefold()
    if re.search(r"\b(?:line|leader|pe|fc|fluoro|braid|xbraid|g-soul|grandmax|waker)\b", haystack):
        return Decimal("380"), Decimal("1280")
    if re.search(r"\b(?:jig|popper|slim|minnow|lure|slalom|pencil|metal|slow|sinking)\b", haystack):
        return Decimal("220"), Decimal("980")
    if re.search(
        r"\b(?:hook|ring|snap|swivel|sinker|lead|assist|split|clip|stopper|stake|peg|carabiner|rope|cord|repair kit)\b",
        haystack,
    ):
        return Decimal("80"), Decimal("480")
    if re.search(r"\b(?:lantern|headlamp|stove|burner|cookset|kettle|grill|tableware|mug)\b", haystack):
        return Decimal("500"), Decimal("2800")
    if re.search(r"\b(?:sleeping bag|sleeping pad|camp mat|air mat|cot|chair|table|bench)\b", haystack):
        return Decimal("900"), Decimal("5200")
    if re.search(
        r"\b(?:reel|rod|pole|net|bag|box|vest|wader|tent|tarp|canopy|cooler|power station|solar panel|backpack)\b",
        haystack,
    ):
        return Decimal("1800"), Decimal("9800")
    return Decimal("500"), Decimal("2500")


def generate_fake_list_price(code: str, name: str = "", spec1: str = "") -> Decimal:
    low, high = _price_band(name, spec1)
    ratio = _hash_ratio(f"{code}|{name}|{spec1}")
    generated = low + ((high - low) * ratio)
    return _round_to_nearest_10(generated)


def resolve_fake_list_price(
    amount: Any,
    *,
    code: str,
    name: str = "",
    spec1: str = "",
) -> Decimal:
    existing = _decimal(amount)
    if existing > 0:
        return existing
    return generate_fake_list_price(code, name, spec1)


def resolve_fake_vip_price(list_price: Any) -> Decimal:
    return _round_to_nearest_10(_decimal(list_price) * VIP_PRICE_RATIO)
