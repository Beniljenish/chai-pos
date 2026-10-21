"""The AI helpers' one door (README, "9.16").

Every AI feature asks a model for **structured JSON** and then checks it in code. The model
proposes and explains; it never writes stock, money or bills. Three safeguards live here so no
feature can forget them: a key check, a per-shop daily ceiling, and a seam for tests.

Without ANTHROPIC_API_KEY the helpers answer "not switched on". With FAKE_AI (local only) a
rule-based stand-in answers, so the screens can be tried and tested without a key or cost.
"""

import base64
import json
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import business_date
from app.models import AiUsage


class AiError(Exception):
    """Something the owner can be told in one line."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def fake_on() -> bool:
    s = get_settings()
    return s.fake_ai and not s.anthropic_api_key


def enabled() -> bool:
    return bool(get_settings().anthropic_api_key)


def available() -> bool:
    return enabled() or fake_on()


# A backend takes (task, system, content, schema) and returns the parsed JSON object.
Backend = Callable[[str, str, list[dict], dict], dict]
_backend: Backend | None = None


def set_backend(fn: Backend | None) -> None:
    """Tests install a function here; None puts the real one back."""
    global _backend
    _backend = fn


def _spend(db: Session, today: date | None = None) -> None:
    """One call against today's ceiling. Counted before the model is asked, so a failing model
    cannot be used to run past it."""
    limit = get_settings().ai_daily_limit
    day = today or business_date()
    row = db.scalar(select(AiUsage).where(AiUsage.day == day).with_for_update())
    if row is None:
        row = AiUsage(day=day, calls=0)
        db.add(row)
        db.flush()
    if row.calls >= limit:
        raise AiError(f"Today's {limit} AI questions for this shop are used up. Try tomorrow.", 429)
    row.calls += 1
    db.flush()


def calls_today(db: Session) -> tuple[int, int]:
    row = db.scalar(select(AiUsage).where(AiUsage.day == business_date()))
    return (row.calls if row else 0), get_settings().ai_daily_limit


def run(
    db: Session, *, task: str, system: str, content: list[dict], schema: dict, spend: bool = True
) -> dict:
    """Ask for JSON that matches `schema`. Raises AiError with a plain message."""
    if not available() and _backend is None:
        raise AiError("The AI helpers are not switched on for this app yet.", 503)
    if spend:
        _spend(db)
        db.commit()  # keep the count even if the model call fails
    if _backend is not None:
        return _backend(task, system, content, schema)
    if fake_on():
        return _LocalFake.answer(task, content)
    return _ask_claude(system, content, schema)


_http_client: Any = None  # tests put a mock transport here; None = the SDK's own


def _ask_claude(system: str, content: list[dict], schema: dict) -> dict:
    import anthropic  # imported here so the rest of the app never needs the package to start

    s = get_settings()
    extra = {"http_client": _http_client} if _http_client is not None else {}
    client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=45.0, max_retries=1, **extra)
    try:
        resp = client.messages.create(
            model=s.ai_model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": schema},
            },
        )
    except anthropic.RateLimitError:
        raise AiError("The AI service is busy. Try again in a minute.", 503) from None
    except anthropic.APIConnectionError:
        raise AiError(
            "Could not reach the AI service. Check the internet and try again.", 503
        ) from None
    except anthropic.APIStatusError as e:
        raise AiError(f"The AI service refused the request ({e.status_code}).", 502) from None
    if resp.stop_reason == "refusal":
        raise AiError("The AI service declined this request.", 422)
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        raise AiError("The AI answer could not be read. Try again.", 502) from None


# ---- helpers every feature uses to check what the model said -----------------------------------

UNIT_TO_BASE = {  # what the model may say -> (base unit it measures, factor)
    "ml": ("ml", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "g": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)),
    "piece": ("piece", Decimal(1)),
    "dozen": ("piece", Decimal(12)),
}


def to_decimal(text: Any, places: str = "0.001") -> Decimal | None:
    try:
        d = Decimal(str(text).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d < 0:
        return None
    return d.quantize(Decimal(places))


def rupees_to_paise(text: Any) -> int | None:
    """ "480" or "480.50" to paise, never through a float."""
    d = to_decimal(text, "0.01")
    return None if d is None else int(d * 100)


def image_block(data: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode(),
        },
    }


# ---- the local stand-in --------------------------------------------------------------------------

_TA_DIGITS = str.maketrans("௦௧௨௩௪௫௬௭௮௯", "0123456789")
_TA_NUMBERS = {  # the few spoken numbers worth guessing when speech recognition wrote words
    "ஒரு": 1, "ஒன்று": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5, "பத்து": 10,
    "இருபது": 20, "முப்பது": 30, "ஐம்பது": 50, "நூறு": 100,
}  # fmt: skip
_TA_NAMES = {  # a few shop words, so the pretend model can find the stock item from Tamil
    "milk": ["பால்"], "sugar": ["சர்க்கரை", "சீனி"], "tea": ["தேயிலை", "டீ தூள்", "டீத்தூள்"],
    "ginger": ["இஞ்சி"], "cardamom": ["ஏலக்காய்"], "orange": ["ஆரஞ்சு"], "lemon": ["எலுமிச்சை"],
    "cup": ["கப்"], "water": ["தண்ணீர்"], "mint": ["புதினா"],
}  # fmt: skip
_TA_DISH = {  # word for word; what it does not know stays in English
    "tea": "டீ", "masala": "மசாலா", "juice": "ஜூஸ்", "orange": "ஆரஞ்சு", "ginger": "இஞ்சி",
    "cardamom": "ஏலக்காய்", "milk": "பால்", "coffee": "காபி", "lemon": "எலுமிச்சை",
    "strong": "கடுமையான", "fresh": "புதிய", "with": "உடன்", "and": "மற்றும்", "sugar": "சர்க்கரை",
}  # fmt: skip
_UNIT_WORDS = {
    "litre": "l", "liter": "l", "litres": "l", "liters": "l", "l": "l", "லிட்டர்": "l",
    "ml": "ml", "kg": "kg", "kilo": "kg", "கிலோ": "kg", "g": "g", "gram": "g", "grams": "g",
    "கிராம்": "g", "piece": "piece", "pieces": "piece", "pcs": "piece", "dozen": "dozen",
    "packet": "piece", "packets": "piece",
}  # fmt: skip


class _LocalFake:
    """Rule-based, deterministic. Good enough to show every screen working; the real model is
    what reads real Tamil and real bills."""

    @classmethod
    def answer(cls, task: str, content: list[dict]) -> dict:
        payload = json.loads(next(b["text"] for b in content if b["type"] == "text"))
        return getattr(cls, task)(payload)

    @staticmethod
    def purchase(p: dict) -> dict:
        text = p["text"].translate(_TA_DIGITS)
        for word, n in _TA_NUMBERS.items():
            text = text.replace(word, str(n))
        names = {i["name"].lower(): i for i in p["ingredients"]}
        tamil = {
            word: i
            for i in p["ingredients"]
            for english, words in _TA_NAMES.items()
            if english in i["name"].lower()
            for word in words
        }
        lines = []
        for chunk in re.split(r"[;\n]|\band\b|,(?=\s*\d)", text):
            nums = re.findall(r"\d+(?:\.\d+)?", chunk)
            if not nums:
                continue
            unit = next(  # split on spaces: Tamil vowel signs are not "word" characters to \w
                (_UNIT_WORDS[w] for w in re.split(r"[\s,.;]+", chunk.lower()) if w in _UNIT_WORDS),
                "piece",
            )
            found = None
            low = chunk.lower()
            for nm, ing in {**names, **tamil}.items():
                if nm in low:
                    found = ing
                    break
            money = re.search(r"(\d+(?:\.\d+)?)\s*(?:rs|rupees?|ரூபாய்|₹)", low) or re.search(
                r"(?:rs|₹)\s*(\d+(?:\.\d+)?)", low
            )
            qty = nums[0]
            total = money.group(1) if money else (nums[-1] if len(nums) > 1 else "0")
            lines.append(
                {
                    "heard_name": found["name"] if found else chunk.strip()[:40],
                    "ingredient_id": found["id"] if found else None,
                    "qty": qty,
                    "unit": unit,
                    "total_rupees": total,
                }
            )
        sup = re.search(r"from\s+([A-Za-z ]{3,30})", p["text"])
        return {"supplier": sup.group(1).strip() if sup else "", "lines": lines,
                "bill_total_rupees": None}  # fmt: skip

    @staticmethod
    def bill(p: dict) -> dict:
        raw = p["ingredients"]
        lines = [
            {
                "heard_name": i["name"],
                "ingredient_id": i["id"],
                "qty": "10",
                "unit": {"ml": "l", "g": "kg", "piece": "piece"}[i["base_unit"]],
                "total_rupees": "240",
            }
            for i in raw[:1]
        ]
        return {"supplier": "Pretend supplier", "lines": lines, "bill_total_rupees": "240"}

    @staticmethod
    def translate(p: dict) -> dict:
        def tamil(text: str) -> str:
            words = [_TA_DISH.get(w.lower().strip(",."), w) for w in text.split()]
            return " ".join(words)

        return {"name_ta": tamil(p["name"]), "description_ta": tamil(p["description"])}

    @staticmethod
    def explain(p: dict) -> dict:
        stock = [f for f in p["facts"] if f["kind"] == "stock"]
        others = [f for f in p["facts"] if f["kind"] != "stock"]
        first = stock[0]["text"] if stock else "Nothing was short."
        summary = (
            f"{first} {len(others)} other things happened that day that may explain it."
            if stock and others
            else first
        )
        reasons = [{"fact_id": f["id"], "text": f["text"]} for f in others[:3]] if stock else []
        return {"summary": summary, "reasons": reasons}

    @staticmethod
    def pick(p: dict) -> dict:
        q = p["question"].lower()
        report = "unknown"
        for words, name in (
            (("wast", "வீண்"), "wastage"),
            (("void", "cancel", "ரத்து"), "voids"),
            (("upi", "razorpay"), "upi"),
            (("gst", "turnover", "registration"), "gst"),
            (("low", "stock", "reorder", "இருப்பு", "குறைவு"), "low_stock"),
            (("best", "top", "most", "அதிகம்", "அதிகமாக"), "top_items"),
            (("sale", "sell", "sold", "takings", "revenue", "விற்பனை", "வருமானம்"), "sales"),
        ):
            if any(w in q for w in words):
                report = name
                break
        period = "today"
        for words, name in (
            (("yesterday", "நேற்று"), "yesterday"),
            (("week", "வாரம்"), "last_7_days"),
            (("30", "month", "மாதம்"), "last_30_days"),
        ):
            if any(w in q for w in words):
                period = name
                break
        return {"report": report, "period": period}

    @staticmethod
    def say(p: dict) -> dict:
        return {"answer": " ".join(p["lines"])}
