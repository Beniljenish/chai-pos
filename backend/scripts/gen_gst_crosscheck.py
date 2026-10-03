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
                "gst_rate_bp": rng.choice([0, 25, 300, 500, 1200, 1800, 2800]),
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


if __name__ == "__main__":
    OUT.write_text(json.dumps({"seed": 2026, "cases": build()}, separators=(",", ":")) + "\n")
    print(f"wrote {OUT}")
