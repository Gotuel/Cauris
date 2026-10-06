from decimal import Decimal, ROUND_HALF_UP


def round_to_minor_unit(value: Decimal, minor_unit: int) -> Decimal:
    """Round a Decimal for the configured currency precision."""
    quantizer = Decimal("1").scaleb(-minor_unit)
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def convert_minor_units(amount: int, from_minor_unit: int, to_minor_unit: int, rate: Decimal) -> int:
    """Convert a minor-unit amount using a Decimal rate and explicit rounding."""
    from_decimal = Decimal(amount) / (Decimal(10) ** from_minor_unit)
    converted = from_decimal * rate
    return int((converted * (Decimal(10) ** to_minor_unit)).to_integral_value(ROUND_HALF_UP))


def convert_rate(amount: Decimal, rate: Decimal) -> Decimal:
    """Apply a conversion to a Decimal amount."""
    return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
