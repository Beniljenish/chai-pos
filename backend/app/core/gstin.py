"""GSTIN validation: format, state code and the check digit.

The 15th character is a mod-36 checksum of the first 14 (the same scheme the
GST portal uses), so a single mistyped character is caught here instead of
being printed on every tax invoice.
"""

import re

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FORMAT = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
# 01-38 are states and union territories (38 = Ladakh); 97 other territory; 99 centre.
VALID_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}


class GstinError(ValueError):
    pass


def check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def normalise_gstin(raw: str) -> str:
    """Upper-case, strip spaces, and validate; raises GstinError with a plain reason."""
    g = re.sub(r"\s+", "", raw).upper()
    if len(g) != 15:
        raise GstinError("A GSTIN has 15 characters")
    if not _FORMAT.match(g):
        raise GstinError("That is not a GSTIN (expected like 33ABCDE1234F1Z7)")
    if g[:2] not in VALID_STATE_CODES:
        raise GstinError(f"{g[:2]} is not an Indian state code")
    if check_digit(g[:14]) != g[14]:
        raise GstinError(
            "The GSTIN's last character does not match; a character is probably mistyped"
        )
    return g
