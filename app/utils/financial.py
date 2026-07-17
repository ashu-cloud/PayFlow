from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Iterable

ADVANCE_RATE = Decimal("0.10")

def round_to_2dp(val: Union[Decimal, float, int, str]) -> Decimal:
    """Rounds any numerical input to 2 decimal places using ROUND_HALF_UP."""
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def calc_advance(earning: Union[Decimal, float, int, str]) -> Decimal:
    """Calculates 10% advance payout for a pending sale."""
    earning_dec = round_to_2dp(earning)
    return round_to_2dp(earning_dec * ADVANCE_RATE)

def calc_final_for_sale(
    status: str,
    earning: Union[Decimal, float, int, str],
    advance_paid: Union[Decimal, float, int, str],
) -> Decimal:
    """Calculates final contribution for a sale based on reconciliation status.
    - approved -> earning - advance_paid
    - rejected -> -advance_paid (clawback)
    """
    earning_dec = round_to_2dp(earning)
    advance_dec = round_to_2dp(advance_paid)

    if status == "approved":
        return round_to_2dp(earning_dec - advance_dec)
    elif status == "rejected":
        return round_to_2dp(-advance_dec)
    else:
        raise ValueError(f"Invalid reconciliation status for final payout calculation: {status}")

def sum_amounts(amounts: Iterable[Union[Decimal, float, int, str]]) -> Decimal:
    """Pre-rounds each element before summing to ensure exact decimal math."""
    total = Decimal("0.00")
    for a in amounts:
        total += round_to_2dp(a)
    return round_to_2dp(total)
