"""Allergy tags on dishes (README, "9.21"): a fixed list, so a filter means the same thing on every
outlet's menu. A tag is the outlet's statement, not a guarantee: the page says so."""

CODES = ["nuts", "milk", "gluten", "egg", "soy", "fish", "shellfish", "sesame"]


def clean(codes: list[str]) -> list[str]:
    bad = [c for c in codes if c not in CODES]
    if bad:
        raise ValueError(f"Unknown allergy tag: {bad[0]}")
    return [c for c in CODES if c in codes]  # fixed order, no repeats


def to_text(codes: list[str]) -> str:
    return ",".join(clean(codes))


def from_text(text: str) -> list[str]:
    return [c for c in (text or "").split(",") if c in CODES]
