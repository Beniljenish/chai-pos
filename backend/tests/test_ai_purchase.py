"""Speak a purchase / photograph a bill into a stock-in draft (services/ai_purchase.py).

The model is replaced by a stand-in that says whatever the test needs, so these tests check
what the SERVER does with an answer: checks it, converts it, refuses to trust it."""

import base64
import json

from app.core.config import get_settings
from app.services import ai
from tests.conftest import build_catalogue, make_shop

API = "/api/v1"


def _says(**answer):
    seen = {}

    def backend(task, system, content, schema):
        seen.update(task=task, system=system, content=content)
        return {"supplier": "", "bill_total_rupees": "", "lines": [], **answer}

    ai.set_backend(backend)
    return seen


def _line(cat_item, qty="20", unit="l", total="480", name="milk"):
    return {
        "heard_name": name,
        "ingredient_id": cat_item["id"],
        "qty": qty,
        "unit": unit,
        "total_rupees": total,
    }


def _draft(client, shop, text="20 litre milk 480 rupees"):
    return client.post(f"{API}/ai/purchase-draft", json={"text": text}, headers=shop.owner_h)


def test_without_a_key_it_says_not_switched_on(client, shop_a):
    build_catalogue(client, shop_a)
    r = _draft(client, shop_a)
    assert r.status_code == 503 and "not switched on" in r.json()["detail"]
    status = client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()
    assert status["on"] is False and status["pretend"] is False


def test_only_the_owner_may_use_it(client, shop_a):
    for path, body in (
        ("purchase-draft", {"text": "20 litre milk"}),
        ("bill-draft", {"image_base64": "A" * 40, "media_type": "image/png"}),
    ):
        assert client.post(f"{API}/ai/{path}", json=body).status_code == 401
        r = client.post(f"{API}/ai/{path}", json=body, headers=shop_a.cashier_h)
        assert r.status_code == 403
    assert client.get(f"{API}/ai/status", headers=shop_a.cashier_h).status_code == 403


def test_a_spoken_purchase_becomes_base_units_and_paise(client, shop_a):
    cat = build_catalogue(client, shop_a)
    seen = _says(supplier="Ravi Dairy", lines=[_line(cat.milk)])
    r = _draft(client, shop_a)
    assert r.status_code == 200, r.text
    body = r.json()
    (ln,) = body["lines"]
    assert ln["ingredient_id"] == cat.milk["id"] and ln["ingredient_name"] == "Milk"
    assert ln["base_qty"] == "20000.000" and ln["base_unit"] == "ml"  # 20 litres in ml
    assert ln["cost_paise"] == 48000 and ln["problems"] == []
    assert body["supplier"] == "Ravi Dairy" and body["lines_total_paise"] == 48000
    # the model was told about this shop's stock, and the note is passed as data
    sent = json.loads(seen["content"][0]["text"])
    assert {i["name"] for i in sent["ingredients"]} >= {"Milk", "Sugar", "Tea powder"}
    assert "Tea decoction" not in {i["name"] for i in sent["ingredients"]}  # batches are made


def test_money_never_goes_through_a_float(client, shop_a):
    cat = build_catalogue(client, shop_a)
    _says(lines=[_line(cat.sugar, qty="2.5", unit="kg", total="112.35")])
    (ln,) = _draft(client, shop_a).json()["lines"]
    assert ln["base_qty"] == "2500.000" and ln["cost_paise"] == 11235


def test_what_cannot_be_proved_is_flagged_not_trusted(client, shop_a, shop_b):
    cat = build_catalogue(client, shop_a)
    other = build_catalogue(client, shop_b)
    _says(
        lines=[
            _line(cat.milk, unit="kg"),  # milk is counted in ml
            _line(other.sugar, name="sugar"),  # another shop's ingredient
            {**_line(cat.sugar), "ingredient_id": "not-a-uuid", "qty": "lots"},
            _line(cat.tea_powder, total="0"),  # no price heard
            _line(cat.decoction),  # a batch item is never bought
        ]
    )
    lines = _draft(client, shop_a).json()["lines"]
    assert "counted in ml, not kg" in lines[0]["problems"][0] and lines[0]["base_qty"] is None
    assert lines[1]["ingredient_id"] is None and "Pick which stock item" in lines[1]["problems"][0]
    assert lines[2]["ingredient_id"] is None and len(lines[2]["problems"]) >= 2
    assert "No price was heard: type it" in lines[3]["problems"]
    assert lines[4]["ingredient_id"] is None  # the decoction is not on the buyable list


def test_the_bills_printed_total_is_checked_against_the_lines(client, shop_a):
    cat = build_catalogue(client, shop_a)
    _says(lines=[_line(cat.milk), _line(cat.sugar, "5", "kg", "225", "sugar")],
          bill_total_rupees="705")  # fmt: skip
    ok = _draft(client, shop_a).json()
    assert ok["lines_total_paise"] == 70500 and ok["total_matches"] is True
    _says(lines=[_line(cat.milk)], bill_total_rupees="500")
    assert _draft(client, shop_a).json()["total_matches"] is False
    _says(lines=[_line(cat.milk)])
    assert _draft(client, shop_a).json()["total_matches"] is None


def test_a_negative_or_nonsense_number_is_not_accepted(client, shop_a):
    cat = build_catalogue(client, shop_a)
    _says(lines=[_line(cat.milk, qty="-5", total="-10"), _line(cat.milk, qty="NaN", total="inf")])
    for ln in _draft(client, shop_a).json()["lines"]:
        assert ln["base_qty"] is None and ln["cost_paise"] == 0 and ln["problems"]


def test_a_shop_has_a_daily_ceiling_and_another_shop_is_unaffected(client, shop_a, monkeypatch):
    build_catalogue(client, shop_a)
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 2)
    _says()
    assert _draft(client, shop_a).status_code == 200
    assert _draft(client, shop_a).status_code == 200
    third = _draft(client, shop_a)
    assert third.status_code == 429 and "used up" in third.json()["detail"]
    other = make_shop(client, "Shop Z")
    assert _draft(client, other).status_code == 200
    s = client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()
    assert s["used_today"] == 2 and s["daily_limit"] == 2


def _photo(client, shop, media="image/png", data=None):
    raw = data if data is not None else base64.b64encode(b"\x89PNG" + b"0" * 40).decode()
    return client.post(
        f"{API}/ai/bill-draft",
        json={"image_base64": raw, "media_type": media},
        headers=shop.owner_h,
    )


def test_a_bill_photo_is_sent_to_the_model_and_checked_like_speech(client, shop_a):
    cat = build_catalogue(client, shop_a)
    seen = _says(supplier="Ravi Dairy", lines=[_line(cat.milk)], bill_total_rupees="480")
    r = _photo(client, shop_a)
    assert r.status_code == 200, r.text
    assert r.json()["total_matches"] is True and r.json()["lines"][0]["base_qty"] == "20000.000"
    assert seen["task"] == "bill" and seen["content"][0]["type"] == "image"
    assert seen["content"][0]["source"]["media_type"] == "image/png"


def test_a_bad_photo_is_refused_before_the_model_is_asked(client, shop_a):
    _says()
    assert _photo(client, shop_a, media="application/pdf").status_code == 422
    assert _photo(client, shop_a, data="!!!not base64!!!" * 5).status_code == 422
    big = base64.b64encode(b"0" * (5 * 1024 * 1024 + 1)).decode()
    assert _photo(client, shop_a, data=big).status_code == 413
    assert client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()["used_today"] == 0


def test_the_pretend_model_understands_english_and_tamil_numbers(client, shop_a, monkeypatch):
    cat = build_catalogue(client, shop_a)
    monkeypatch.setattr(get_settings(), "fake_ai", True)
    r = _draft(client, shop_a, "20 litres milk 480 rupees from Ravi Dairy")
    (ln,) = r.json()["lines"]
    assert ln["ingredient_id"] == cat.milk["id"] and ln["base_qty"] == "20000.000"
    assert ln["cost_paise"] == 48000 and r.json()["supplier"] == "Ravi Dairy"
    assert client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()["pretend"] is True
    t = _draft(client, shop_a, "இருபது லிட்டர் பால் 480 ரூபாய்").json()["lines"]
    assert t[0]["ingredient_id"] == cat.milk["id"] and t[0]["base_qty"] == "20000.000"
    two = _draft(client, shop_a, "5 kg sugar 225 rupees and 10 litre milk 240 rupees").json()
    assert len(two["lines"]) == 2 and two["lines_total_paise"] == 46500


def test_the_pretend_model_refuses_to_start_with_a_real_database(monkeypatch):
    import pytest

    from app.core.config import Settings

    with pytest.raises(ValueError, match="FAKE_AI"):
        Settings(
            fake_ai=True,
            database_url="postgresql+psycopg://u:p@db.example.com:5432/x",
            jwt_secret="x" * 40,
        )


# ---------------------------------------------------------------- dish names in Tamil
def test_dish_translation_is_a_suggestion_the_owner_then_saves(client, shop_a):
    cat = build_catalogue(client, shop_a)
    seen = _says(name_ta="மசாலா டீ", description_ta="இஞ்சி சேர்த்த வலுவான டீ")
    r = client.post(
        f"{API}/ai/translate-dish",
        json={"name": "Masala tea", "description": "Strong tea with ginger"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 200 and r.json()["name_ta"] == "மசாலா டீ"
    assert seen["task"] == "translate"
    # nothing was saved by asking
    item = client.get(f"{API}/menu-items/{cat.tea['id']}", headers=shop_a.owner_h).json()
    assert item["name_ta"] == ""
    # saving is an ordinary menu edit, and customers see it
    patch = {"name_ta": "மசாலா டீ", "description_ta": "இஞ்சி சேர்த்த வலுவான டீ"}
    client.patch(f"{API}/menu-items/{cat.tea['id']}", json=patch, headers=shop_a.owner_h)
    got = client.get(f"{API}/menu-items/{cat.tea['id']}", headers=shop_a.owner_h).json()
    assert got["name_ta"] == "மசாலா டீ" and got["description_ta"].startswith("இஞ்சி")
    assert (
        client.patch(
            f"{API}/menu-items/{cat.tea['id']}", json=patch, headers=shop_a.cashier_h
        ).status_code
        == 403
    )


def test_an_empty_description_stays_empty_and_only_the_owner_translates(client, shop_a):
    _says(name_ta="டீ", description_ta="should be dropped")
    ok = client.post(
        f"{API}/ai/translate-dish", json={"name": "Tea", "description": ""}, headers=shop_a.owner_h
    )
    assert ok.json() == {"name_ta": "டீ", "description_ta": ""}
    denied = client.post(f"{API}/ai/translate-dish", json={"name": "Tea"}, headers=shop_a.cashier_h)
    assert denied.status_code == 403


# ---------------------------------------------------------------- the real model, over a fake wire
def _wire(monkeypatch, handler):
    """Point the real client at a stand-in server, to check the request the app really builds."""
    import anthropic
    import httpx2

    from app.services import ai as ai_mod

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test-not-real")
    monkeypatch.setattr(
        ai_mod,
        "_http_client",
        anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )


def _reply(text, stop="end_turn"):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def test_the_real_request_asks_for_json_in_the_schema_at_low_effort(client, shop_a, monkeypatch):
    import httpx2

    cat = build_catalogue(client, shop_a)
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        answer = {"supplier": "", "bill_total_rupees": "", "lines": [_line(cat.milk)]}
        return httpx2.Response(200, json=_reply(json.dumps(answer)))

    _wire(monkeypatch, handler)
    r = _draft(client, shop_a)
    assert r.status_code == 200 and r.json()["lines"][0]["cost_paise"] == 48000
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] >= 1000
    assert body["output_config"]["effort"] == "low"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and "lines" in fmt["schema"]["properties"]
    assert "Never guess between two candidates" in body["system"]
    assert "thinking" not in body and "temperature" not in body  # rejected by the newest models
    assert seen["headers"]["authorization"] == "Bearer sk-ant-test-not-real"
    assert json.loads(body["messages"][0]["content"][0]["text"])["text"].startswith("20 litre")


def test_a_refusal_a_busy_service_and_a_garbled_answer_are_told_plainly(
    client, shop_a, monkeypatch
):
    import httpx2

    build_catalogue(client, shop_a)
    mode = {"now": "refuse"}

    def handler(request):
        if mode["now"] == "refuse":
            return httpx2.Response(200, json=_reply("", stop="refusal"))
        if mode["now"] == "busy":
            return httpx2.Response(
                429,
                json={
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": "slow down"},
                },
            )
        return httpx2.Response(200, json=_reply("this is not json"))

    _wire(monkeypatch, handler)
    refused = _draft(client, shop_a)
    assert refused.status_code == 422 and "declined" in refused.json()["detail"]
    mode["now"] = "busy"
    busy = _draft(client, shop_a)
    assert busy.status_code == 503 and "busy" in busy.json()["detail"]
    mode["now"] = "garbled"
    garbled = _draft(client, shop_a)
    assert garbled.status_code == 502 and "could not be read" in garbled.json()["detail"]
    # every try used an allowance: a failing model cannot be used to run past the ceiling
    assert client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()["used_today"] == 3


def test_a_bill_photo_goes_over_the_wire_as_an_image_block(client, shop_a, monkeypatch):
    import httpx2

    cat = build_catalogue(client, shop_a)
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        answer = {"supplier": "", "bill_total_rupees": "480", "lines": [_line(cat.milk)]}
        return httpx2.Response(200, json=_reply(json.dumps(answer)))

    _wire(monkeypatch, handler)
    raw = base64.b64encode(b"\x89PNG" + b"0" * 40).decode()
    r = client.post(
        f"{API}/ai/bill-draft",
        json={"image_base64": raw, "media_type": "image/png"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 200 and r.json()["total_matches"] is True
    first, second = seen["body"]["messages"][0]["content"]
    assert first["type"] == "image" and first["source"]["data"] == raw
    assert second["type"] == "text"
