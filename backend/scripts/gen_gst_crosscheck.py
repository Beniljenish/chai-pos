"""Generate shared/gst_crosscheck.json: random bills with the PYTHON answers.

The TypeScript tests must reproduce every answer exactly, which is what makes a
server/device totals mismatch practically impossible. tests/test_gst.py checks
this file is still in sync with gst.py, so a Python change without regenerating
fails CI.

Usage: python -m scripts.gen_gst_crosscheck
"""

import json
import random
from pathlib import Path

from app.models import GstType
from app.services.gst import LineIn, compute_bill

OUT = Path(__file__).parents[2] / "shared" / "gst_crosscheck.json"


def build(seed: int = 2026, n: int = 2000) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        lines = [
            {
                "unit_price_paise": rng.choice(
                    [0, 1, 5, 99, 1000, 1050, 1500, 2000, 3333, 6000, rng.randint(0, 99_999)]
                ),
                "qty": rng.randint(1, 50),
                "gst_rate_bp": rng.choice([0, 25, 300, 500, 1200, 1800, 2800, 4000]),
                "tax_inclusive": rng.random() < 0.7,
                "modifier_deltas_paise": [
                    rng.choice([0, 500, 1000]) for _ in range(rng.randint(0, 2))
                ],
            }
            for _ in range(rng.randint(1, 8))
        ]
        gst_type = rng.choice([t.value for t in GstType])
        bill = compute_bill(
            [
                LineIn(
                    ln["unit_price_paise"],
                    ln["qty"],
                    ln["gst_rate_bp"],
                    ln["tax_inclusive"],
                    tuple(ln["modifier_deltas_paise"]),
                )
                for ln in lines
            ],
            GstType(gst_type),
        )
        cases.append(
            {
                "gst_type": gst_type,
                "lines": lines,
                "expect": {
                    "lines": [
                        [lt.gross, lt.taxable, lt.cgst, lt.sgst, lt.total] for lt in bill.lines
                    ],
                    "bill": [
                        bill.taxable,
                        bill.cgst,
                        bill.sgst,
                        bill.subtotal,
                        bill.round_off,
                        bill.total,
                    ],
                },
            }
        )
    return cases


def build_discounted(seed: int = 2027, n: int = 1000) -> list[dict]:
    """Bills with line and bill discounts (Phase 6). Lines answer
    [gross, discount, taxable, cgst, sgst, total]; the bill answers
    [discount, taxable, cgst, sgst, subtotal, round_off, total]."""
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        lines = []
        for _ in range(rng.randint(1, 6)):
            unit = rng.choice([1000, 1050, 2000, 3333, 6000, rng.randint(1, 99_999)])
            qty = rng.randint(1, 20)
            deltas = [rng.choice([0, 500, 1000]) for _ in range(rng.randint(0, 2))]
            gross = (unit + sum(deltas)) * qty
            lines.append(
                {
                    "unit_price_paise": unit,
                    "qty": qty,
                    "gst_rate_bp": rng.choice([0, 25, 300, 500, 1200, 1800, 2800, 4000]),
                    "tax_inclusive": rng.random() < 0.7,
                    "modifier_deltas_paise": deltas,
                    "discount_paise": rng.choice([0, 0, rng.randint(0, gross)]),
                }
            )
        left = sum(
            (ln["unit_price_paise"] + sum(ln["modifier_deltas_paise"])) * ln["qty"]
            - ln["discount_paise"]
            for ln in lines
        )
        bill_discount = rng.choice([0, rng.randint(0, left), rng.randint(0, min(left, 5000))])
        gst_type = rng.choice([t.value for t in GstType])
        bill = compute_bill(
            [
                LineIn(
                    ln["unit_price_paise"],
                    ln["qty"],
                    ln["gst_rate_bp"],
                    ln["tax_inclusive"],
                    tuple(ln["modifier_deltas_paise"]),
                    ln["discount_paise"],
                )
                for ln in lines
            ],
            GstType(gst_type),
            bill_discount,
        )
        cases.append(
            {
                "gst_type": gst_type,
                "bill_discount_paise": bill_discount,
                "lines": lines,
                "expect": {
                    "lines": [
                        [lt.gross, lt.discount, lt.taxable, lt.cgst, lt.sgst, lt.total]
                        for lt in bill.lines
                    ],
                    "bill": [
                        bill.discount,
                        bill.taxable,
                        bill.cgst,
                        bill.sgst,
                        bill.subtotal,
                        bill.round_off,
                        bill.total,
                    ],
                },
            }
        )
    return cases


if __name__ == "__main__":
    data = {
        "seed": 2026,
        "cases": build(),
        "discount_seed": 2027,
        "discount_cases": build_discounted(),
    }
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"wrote {OUT}")
