"""The AI helpers' routes (README, "9.16"). Owner only: they read the shop's stock and takings,
and each call spends the shop's daily allowance."""

import base64
import binascii
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import Caller, require_owner
from app.core.time import business_date
from app.services import ai, ai_feedback, ai_insight, ai_purchase, ai_text

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _raise(e: ai.AiError):
    raise HTTPException(e.status, str(e)) from None


class StatusOut(BaseModel):
    on: bool
    pretend: bool
    used_today: int
    daily_limit: int


@router.get("/status", response_model=StatusOut)
def status(caller: Caller = Depends(require_owner)):
    used, limit = ai.calls_today(caller.db)
    return StatusOut(on=ai.available(), pretend=ai.fake_on(), used_today=used, daily_limit=limit)


class PurchaseTextIn(BaseModel):
    text: Annotated[str, Field(min_length=2, max_length=1500)]


class PurchaseBillIn(BaseModel):
    image_base64: Annotated[str, Field(min_length=20, max_length=8_000_000)]
    media_type: str


class DraftLineOut(BaseModel):
    heard_name: str
    ingredient_id: uuid.UUID | None
    ingredient_name: str
    base_unit: str
    base_qty: Decimal | None
    cost_paise: int
    problems: list[str]


class DraftOut(BaseModel):
    supplier: str
    lines: list[DraftLineOut]
    lines_total_paise: int
    bill_total_paise: int | None
    total_matches: bool | None


@router.post("/purchase-draft", response_model=DraftOut)
def purchase_draft(body: PurchaseTextIn, caller: Caller = Depends(require_owner)):
    try:
        return ai_purchase.from_text(caller.db, body.text)
    except ai.AiError as e:
        _raise(e)


@router.post("/bill-draft", response_model=DraftOut)
def bill_draft(body: PurchaseBillIn, caller: Caller = Depends(require_owner)):
    if body.media_type not in PHOTO_TYPES:
        raise HTTPException(422, "Send a JPEG, PNG, WebP or GIF picture")
    try:
        data = base64.b64decode(body.image_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "The picture could not be read") from None
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "The picture is over 5 MB: take it again from further away")
    try:
        return ai_purchase.from_photo(caller.db, data, body.media_type)
    except ai.AiError as e:
        _raise(e)


class TranslateIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: Annotated[str, Field(max_length=200)] = ""


class TranslateOut(BaseModel):
    name_ta: str
    description_ta: str


@router.post("/translate-dish", response_model=TranslateOut)
def translate_dish(body: TranslateIn, caller: Caller = Depends(require_owner)):
    try:
        return ai_text.translate_dish(caller.db, body.name, body.description)
    except ai.AiError as e:
        _raise(e)


Lang = Annotated[str, Field(pattern="^(en|ta)$")]


@router.post("/feedback-summary")
def feedback_summary(
    lang: str = Query(default="en", pattern="^(en|ta)$"), caller: Caller = Depends(require_owner)
) -> dict:
    """What customers wrote about this outlet in the last four weeks, in a few lines."""
    try:
        return ai_feedback.summarise(caller.db, lang)
    except ai.AiError as e:
        _raise(e)


@router.post("/explain-day")
def explain_day(
    day: date | None = Query(default=None, alias="date"),
    lang: str = Query(default="en", pattern="^(en|ta)$"),
    caller: Caller = Depends(require_owner),
) -> dict:
    """Why the stock was off on a day: facts from the records, put into words."""
    try:
        return ai_insight.explain_day(caller.db, day or business_date(), lang)
    except ai.AiError as e:
        _raise(e)


class AskIn(BaseModel):
    question: Annotated[str, Field(min_length=2, max_length=300)]
    lang: Lang = "en"


@router.post("/ask")
def ask(body: AskIn, caller: Caller = Depends(require_owner)) -> dict:
    """Ask a question about the shop. Read-only: the answer comes from fixed reports."""
    try:
        return ai_insight.ask(caller.db, body.question, body.lang)
    except ai.AiError as e:
        _raise(e)
