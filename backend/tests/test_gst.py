"""GST rules: the shared vectors (same file the TypeScript port uses) plus
properties that must hold for ANY input, checked over thousands of random bills.

Pure-function tests: no database needed."""

import json
import random
from dataclasses import asdict
from pathlib import Path

import pytest

from app.models import GstType
from app.services.gst import GstError, LineIn, compute_bill

CASES = json.loads((Path(__file__).parents[2] / "shared" / "gst_cases.json").read_text())


def _lines(raw: list[dict]) -> list[LineIn]:
    return [
        LineIn(
            unit_price_paise=r["unit_price_paise"],
            qty=r["qty"],
            gst_rate_bp=r["gst_rate_bp"],
            tax_inclusive=r["tax_inclusive"],
            modifier_deltas_paise=tuple(r.get("modifier_deltas_paise", ())),
        )
        for r in raw
    ]


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_shared_vector(case):
    bill = compute_bill(_lines(case["lines"]), GstType(case["gst_type"]))
    assert [asdict(lt) for lt in bill.lines] == case["expect_lines"]
    got = asdict(bill)
    got.pop("lines")
    assert got == case["expect_bill"]


@pytest.mark.parametrize("case", CASES["errors"], ids=lambda c: c["name"])
def test_shared_error_vector(case):
    with pytest.raises(GstError):
        compute_bill(_lines(case["lines"]), GstType(case["gst_type"]))


RATES = [0, 25, 300, 500, 1200, 1800, 2800]


def _random_line(rng: random.Random) -> LineIn:
    return LineIn(
        unit_price_paise=rng.choice(
            [0, 1, 99, 1000, 1050, 2000, 3333, 6000, rng.randint(0, 50_000)]
        ),
        qty=rng.randint(1, 20),
        gst_rate_bp=rng.choice(RATES),
        tax_inclusive=rng.random() < 0.7,
        modifier_deltas_paise=tuple(rng.choice([0, 500, 1000]) for _ in range(rng.randint(0, 2))),
    )


def test_properties_hold_for_5000_random_bills():
    rng = random.Random(42)
    for _ in range(5000):
        lines = [_random_line(rng) for _ in range(rng.randint(1, 6))]
        gst_type = rng.choice(list(GstType))
        bill = compute_bill(lines, gst_type)

        for line, lt in zip(lines, bill.lines, strict=True):
            unit = line.unit_price_paise + sum(line.modifier_deltas_paise)
            assert lt.gross == unit * line.qty
            # the parts always add up exactly
            assert lt.taxable + lt.cgst + lt.sgst == lt.total
            assert lt.cgst == lt.sgst and lt.cgst >= 0 and lt.taxable >= 0
            if gst_type != GstType.regular:
                assert lt.cgst == 0 and lt.total == lt.gross
            elif line.tax_inclusive:
                # the customer pays exactly the menu price
                assert lt.total == lt.gross
            else:
                assert lt.taxable == lt.gross
            # each half of the tax is within 1 paise of the exact figure
            if gst_type == GstType.regular and line.gst_rate_bp:
                exact_half = lt.taxable * line.gst_rate_bp / 2 / 10_000
                assert abs(lt.cgst - exact_half) <= 1, (line, lt)

        assert bill.subtotal == sum(lt.total for lt in bill.lines)
        assert bill.total % 100 == 0
        assert -49 <= bill.round_off <= 50
        assert bill.total == bill.subtotal + bill.round_off
        assert bill.taxable + bill.cgst + bill.sgst == bill.subtotal


def test_crosscheck_file_matches_current_python():
    """shared/gst_crosscheck.json holds Python's answers for the TypeScript tests.
    If gst.py changes, regenerate it: python -m scripts.gen_gst_crosscheck"""
    from scripts.gen_gst_crosscheck import OUT, build

    stored = json.loads(OUT.read_text())
    assert stored["cases"] == build(stored["seed"]), "regenerate shared/gst_crosscheck.json"
