from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Stripe's own list of zero-decimal currencies (no minor unit at all --
# "amount" IS the currency's smallest unit, e.g. 100 JPY is just 100, not
# 10000). https://docs.stripe.com/currencies#zero-decimal. PayPal has no
# such currencies in its supported list, so this only matters for the
# Stripe amount<->minor-units conversion, but is centralized here so any
# future PayPal-side zero-decimal support doesn't need a second list.
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
        "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
)
# Currencies with THREE decimal places -- rare, but present in both
# Stripe's and PayPal's currency lists (e.g. Bahraini dinar).
_THREE_DECIMAL_CURRENCIES = frozenset({"bhd", "jod", "kwd", "omr", "tnd"})


def decimal_places(currency: str) -> int:
    code = currency.lower()
    if code in _ZERO_DECIMAL_CURRENCIES:
        return 0
    if code in _THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def to_minor_units(amount: Decimal, currency: str) -> int:
    """Converts a decimal major-unit amount (e.g. Decimal("12.50")) to the
    integer minor-unit amount Stripe's API expects (e.g. 1250 for USD, 12
    for JPY) -- rounds rather than truncates, so a stray sub-cent Decimal
    never silently loses money off the amount actually charged/refunded.
    """
    places = decimal_places(currency)
    scale = Decimal(10) ** places
    return int((amount * scale).to_integral_value(rounding=ROUND_HALF_UP))


def from_minor_units(amount: int, currency: str) -> Decimal:
    """Inverse of to_minor_units -- converts a provider's integer
    minor-unit amount back to a major-unit Decimal."""
    places = decimal_places(currency)
    scale = Decimal(10) ** places
    return Decimal(amount) / scale


def format_major_units(amount: Decimal, currency: str) -> str:
    """Formats a major-unit amount to the fixed-point string PayPal's REST
    API expects for its `value` field -- the right number of decimal
    places for the currency, not always 2."""
    places = decimal_places(currency)
    quantum = Decimal(1).scaleb(-places) if places else Decimal(1)
    return str(amount.quantize(quantum, rounding=ROUND_HALF_UP))
