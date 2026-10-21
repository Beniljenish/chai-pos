# ruff: noqa: F811  (the `day` fixture is imported from the Phase 3 gate and used as an argument)
"""Why the stock is short, and Ask your shop (services/ai_insight.py).

The model is replaced by a stand-in, so these tests pin down what the SERVER guarantees: the
facts and the numbers come from the records, reasons must point at a real fact, a question can
only reach the fixed reports, and the daily allowance is spent once per question."""

import json
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.services import ai
from tests.conftest import FakeDevice, build_catalogue
from tests.test_phase3_gate import _url, day  # noqa: F401

API = "/api/v1"


def _says(**by_task):
    seen = {}

    def backend(task, system, content, schema):
        seen.setdefault(task, []).append(
            {"system": system, "payload": json.loads(content[0]["text"])}
        )
        return (
            by_task[task](seen[task][-1]["payload"]) if callable(by_task[task]) else by_task[task]
        )

    ai.set_backend(backend)
    return seen


def _count_milk_short(client, shop, cat, milk):
    r = client.post(
        _url("counts"),
        json={
            "lines": [
                {
                    "ingredient_id": cat.milk["id"],
                    "packs": [{"pack_unit_id": milk["packet"], "qty": "26"}],
                }
            ]
        },
        headers=shop.cashier_h,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- explain a day
def test_the_facts_come_from_the_records_and_reasons_must_point_at_them(client, shop_a, day):
    cat, device, milk, *_ = day
    _count_milk_short(client, shop_a, cat, milk)
    seen = _says(
        explain=lambda p: {
            "summary": "Milk was short by half a litre.",
            "reasons": [
                {"fact_id": next(f["id"] for f in p["facts"] if f["kind"] == "wastage"),
                 "text": "500 ml of milk was thrown away."},
                {"fact_id": "f999", "text": "Someone stole it."},  # invented: must be dropped
            ],
        }
    )  # fmt: skip
    r = client.post(f"{API}/ai/explain-day", headers=shop_a.owner_h)
    assert r.status_code == 200, r.text
    body = r.json()
    stock = [f for f in body["facts"] if f["kind"] == "stock"]
    assert len(stock) == 1 and stock[0]["amount_paise"] == 2800
    assert stock[0]["text"].startswith("Milk was 0.5 L short: expected 13.5 L, counted 13 L")
    assert {f["kind"] for f in body["facts"]} >= {"stock", "wastage"}
    assert body["summary"] == "Milk was short by half a litre."
    assert len(body["reasons"]) == 1 and body["reasons"][0]["fact_id"] != "f999"
    assert "English" in seen["explain"][0]["system"]


def test_tamil_is_asked_for_by_name_and_a_quiet_day_costs_nothing(client, shop_a):
    build_catalogue(client, shop_a)
    seen = _says(explain={"summary": "x", "reasons": []})
    quiet = client.post(f"{API}/ai/explain-day?lang=ta", headers=shop_a.owner_h).json()
    assert quiet["facts"] == [] and quiet["summary"] == "" and "explain" not in seen
    assert client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()["used_today"] == 0
    device = FakeDevice(client, shop_a)
    b = device.bill([("Masala tea", 1, [])])
    device.sync([b])
    client.post(f"{API}/bills/{b['id']}/void", json={"reason": "other"}, headers=shop_a.owner_h)
    out = client.post(f"{API}/ai/explain-day?lang=ta", headers=shop_a.owner_h).json()
    assert out["facts"][0]["kind"] == "void" and "Tamil" in seen["explain"][0]["system"]
    bad = client.post(f"{API}/ai/explain-day?lang=fr", headers=shop_a.owner_h)
    assert bad.status_code == 422
    assert client.post(f"{API}/ai/explain-day", headers=shop_a.cashier_h).status_code == 403


# ---------------------------------------------------------------- ask your shop
def _sell(client, shop, n=2):
    build_catalogue(client, shop)
    device = FakeDevice(client, shop)
    bills = [device.bill([("Masala tea", 1, [])]) for _ in range(n)]
    bills.append(device.bill([("Orange juice", 1, [])], payment_mode="upi"))
    device.sync(bills)


def test_a_question_runs_a_fixed_report_and_the_answer_is_built_from_its_lines(client, shop_a):
    _sell(client, shop_a)
    seen = _says(
        pick={"report": "sales", "period": "today"},
        say=lambda p: {"answer": "Today: " + p["lines"][0]},
    )
    r = client.post(f"{API}/ai/ask", json={"question": "How much did I sell today?"},
                    headers=shop_a.owner_h)  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"] == "sales" and body["lines"][0] == "Sales ₹100 from 3 bills."
    assert body["answer"] == "Today: Sales ₹100 from 3 bills."
    assert "UPI: ₹60" in body["lines"] and "CASH: ₹40" in body["lines"]
    # the writer was only ever shown the report's lines and the question, not the database
    assert set(seen["say"][0]["payload"]) == {"question", "lines", "language"}


def test_one_question_spends_one_allowance_even_though_it_asks_twice(client, shop_a):
    _sell(client, shop_a)
    _says(pick={"report": "top_items", "period": "today"}, say={"answer": "Masala tea."})
    client.post(f"{API}/ai/ask", json={"question": "best seller?"}, headers=shop_a.owner_h)
    assert client.get(f"{API}/ai/status", headers=shop_a.owner_h).json()["used_today"] == 1


def test_every_fixed_report_runs_and_answers_in_numbers(client, shop_a):
    _sell(client, shop_a)
    first = client.get(f"{API}/ingredients", headers=shop_a.owner_h).json()[0]
    client.post(
        f"{API}/wastage",
        json={"ingredient_id": first["id"], "qty": "100", "reason": "spilled"},
        headers=shop_a.owner_h,
    )
    _says(pick=lambda p: {"report": p["question"], "period": "last_7_days"},
          say=lambda p: {"answer": " | ".join(p["lines"])})  # fmt: skip
    for report in ("sales", "top_items", "wastage", "low_stock", "voids", "upi", "gst"):
        r = client.post(f"{API}/ai/ask", json={"question": report}, headers=shop_a.owner_h)
        assert r.status_code == 200, (report, r.text)
        assert r.json()["report"] == report and r.json()["lines"] and r.json()["answer"]
    top = client.post(f"{API}/ai/ask", json={"question": "top_items"}, headers=shop_a.owner_h)
    # best by takings first: one juice (60) beats two teas (40)
    assert top.json()["lines"][:2] == ["Orange juice: 1 sold (₹60)", "Masala tea: 2 sold (₹40)"]


def test_an_unknown_report_or_a_request_to_change_something_is_not_run(client, shop_a):
    _sell(client, shop_a)
    seen = _says(
        pick=lambda p: {"report": "delete_all_bills", "period": "forever"},
        say={"answer": "never asked"},
    )
    r = client.post(f"{API}/ai/ask", json={"question": "Delete every bill"}, headers=shop_a.owner_h)
    assert r.status_code == 200 and r.json()["report"] == "unknown"
    assert "cannot change anything" in r.json()["answer"] and "say" not in seen
    assert len(client.get(f"{API}/bills", headers=shop_a.owner_h).json()) == 3  # nothing changed


def test_ask_is_owner_only_and_each_shop_sees_only_its_own_numbers(client, shop_a, shop_b):
    _sell(client, shop_a)
    build_catalogue(client, shop_b)
    _says(pick={"report": "sales", "period": "today"}, say=lambda p: {"answer": p["lines"][0]})
    assert client.post(f"{API}/ai/ask", json={"question": "sales"}).status_code == 401
    denied = client.post(f"{API}/ai/ask", json={"question": "sales"}, headers=shop_a.cashier_h)
    assert denied.status_code == 403
    mine = client.post(f"{API}/ai/ask", json={"question": "sales"}, headers=shop_a.owner_h)
    theirs = client.post(f"{API}/ai/ask", json={"question": "sales"}, headers=shop_b.owner_h)
    assert "3 bills" in mine.json()["answer"] and "0 bills" in theirs.json()["answer"]


def test_the_pretend_model_routes_english_and_tamil_questions(client, shop_a, monkeypatch):
    _sell(client, shop_a)
    monkeypatch.setattr(get_settings(), "fake_ai", True)
    for question, report in (
        ("What are my best sellers this week?", "top_items"),
        ("இன்று விற்பனை எவ்வளவு?", "sales"),
        ("how much wastage", "wastage"),
        ("Is stock low?", "low_stock"),
        ("sing me a song", "unknown"),
    ):
        r = client.post(f"{API}/ai/ask", json={"question": question}, headers=shop_a.owner_h)
        assert r.json()["report"] == report, question


def test_the_stand_in_expiry_helper_is_not_confused_by_yesterday(client, shop_a):
    build_catalogue(client, shop_a)
    device = FakeDevice(client, shop_a)
    device.sync(
        [device.bill([("Masala tea", 1, [])], sold_at=datetime.now(UTC) - timedelta(days=1))]
    )
    _says(pick={"report": "sales", "period": "yesterday"}, say=lambda p: {"answer": p["lines"][0]})
    r = client.post(f"{API}/ai/ask", json={"question": "yesterday"}, headers=shop_a.owner_h)
    assert r.json()["answer"].startswith("Sales ₹20 from 1 bills")
