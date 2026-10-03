"""GST for one bill. Pure functions: no database, no clock, no I/O.

All money is integer paise in and out. Inside, we use Decimal with
ROUND_HALF_UP, the rounding people expect on paper (2.5 -> 3). Python's built-in
round() uses banker's rounding (2.5 -> 2), which would make some bills disagree
with a calculator by a paise.

This module has a TypeScript twin in the billing app. Both must pass
shared/gst_cases.json; change the rules in both places or neither.

Rules (see docs/SPEC.md, GST invoicing):
- Tax is computed per LINE on the line's gross (price x qty), not per unit.
- Regular GST, intra-state: CGST and SGST are each half the rate.
- Tax-inclusive prices: the customer pays exactly the menu price. Any paise
  left over from rounding is absorbed by the taxable value.
- Composition / unregistered shops charge no GST.
- The bill total is rounded to the nearest rupee; the difference is round_off.
- Discounts (Phase 6) are given on the invoice, so they reduce the value GST is
  charged on. A line discount comes off that line. A bill discount is shared
  across the lines in proportion to what is left on each (largest remainder, so
  the shares add up to the paise); each line's GST is then worked out on its
  own reduced amount, at its own rate.

Not tax advice: confirm the rules with the shop's CA before go-live.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models import GstType

MAX_RATE_BP = 2800  # 28%, the highest GST slab
BP = Decimal(10_000)  # basis points per 100%


class GstError(ValueError):
    pass


@dataclass(frozen=True)
class LineIn:
    unit_price_paise: int
    qty: int
    gst_rate_bp: int
    tax_inclusive: bool
    modifier_deltas_paise: Sequence[int] = ()
    discount_paise: int = 0  # taken off this line by the cashier


@dataclass(frozen=True)
class LineTotals:
    gross: int  # (unit price + modifier deltas) x qty
    discount: int  # this line's discount plus its share of the bill discount
    taxable: int
    cgst: int
    sgst: int
    total: int  # what this line adds to the bill


@dataclass(frozen=True)
class BillTotals:
    lines: tuple[LineTotals, ...]
    discount: int  # all discounts on the bill
    taxable: int
    cgst: int
    sgst: int
    subtotal: int  # sum of line totals, before rounding to the rupee
    round_off: int  # total - subtotal, between -49 and +50
    total: int  # what the customer pays


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _validate(line: LineIn) -> int:
    """Returns the effective unit price after modifiers."""
    if line.qty <= 0:
        raise GstError("Quantity must be at least 1")
    if line.unit_price_paise < 0:
        raise GstError("Price cannot be negative")
    if not 0 <= line.gst_rate_bp <= MAX_RATE_BP:
        raise GstError(f"GST rate must be between 0 and {MAX_RATE_BP} basis points")
    unit = line.unit_price_paise + sum(line.modifier_deltas_paise)
    if unit < 0:
        raise GstError("Price after modifiers cannot be negative")
    if not 0 <= line.discount_paise <= unit * line.qty:
        raise GstError("A line discount must be between nothing and the line's price")
    return unit


def share_discount(discount: int, amounts: Sequence[int]) -> list[int]:
    """Split a bill discount across lines in proportion to `amounts`. Largest
    remainder: everyone gets the whole paise of their share, and the paise left
    over go to the biggest fractions (the earlier line on a tie)."""
    if discount == 0:
        return [0] * len(amounts)
    whole = sum(amounts)
    if discount < 0 or discount > whole:
        raise GstError("A bill discount must be between nothing and the bill")
    shares = [discount * a // whole for a in amounts]
    rest = [discount * a % whole for a in amounts]
    for i in sorted(range(len(amounts)), key=lambda i: (-rest[i], i))[: discount - sum(shares)]:
        shares[i] += 1
    return shares


def compute_line(line: LineIn, gst_type: GstType, bill_share: int = 0) -> LineTotals:
    gross = _validate(line) * line.qty
    discount = line.discount_paise + bill_share
    net = gross - discount  # what GST is charged on (or included in)

    if gst_type != GstType.regular or line.gst_rate_bp == 0:
        return LineTotals(
            gross=gross, discount=discount, taxable=net, cgst=0, sgst=0, total=net
        )

    rate = Decimal(line.gst_rate_bp)
    half_rate = rate / 2

    if line.tax_inclusive:
        # Back out the tax: net = taxable x (1 + rate)
        taxable = _round(Decimal(net) * BP / (BP + rate))
        cgst = _round(Decimal(taxable) * half_rate / BP)
        sgst = cgst  # same rate on the same base, so always equal
        # Rounding can leave taxable + tax 1 paise off the menu price.
        # The customer must pay exactly the menu price, so taxable absorbs it.
        taxable = net - cgst - sgst
        return LineTotals(
            gross=gross, discount=discount, taxable=taxable, cgst=cgst, sgst=sgst, total=net
        )

    taxable = net
    cgst = _round(Decimal(taxable) * half_rate / BP)
    sgst = cgst
    return LineTotals(
        gross=gross,
        discount=discount,
        taxable=taxable,
        cgst=cgst,
        sgst=sgst,
        total=net + 2 * cgst,
    )


def compute_bill(
    lines: Sequence[LineIn], gst_type: GstType, bill_discount_paise: int = 0
) -> BillTotals:
    if not lines:
        raise GstError("A bill needs at least one line")
    left = [_validate(ln) * ln.qty - ln.discount_paise for ln in lines]
    shares = share_discount(bill_discount_paise, left)
    computed = tuple(
        compute_line(line, gst_type, share) for line, share in zip(lines, shares, strict=True)
    )
    subtotal = sum(lt.total for lt in computed)
    total = _round(Decimal(subtotal) / 100) * 100  # nearest rupee, half up
    return BillTotals(
        lines=computed,
        discount=sum(lt.discount for lt in computed),
        taxable=sum(lt.taxable for lt in computed),
        cgst=sum(lt.cgst for lt in computed),
        sgst=sum(lt.sgst for lt in computed),
        subtotal=subtotal,
        round_off=total - subtotal,
        total=total,
    )
