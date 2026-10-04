"""Shop GST settings: what prints on every bill, so the rules are strict."""

import pytest

from app.core.gstin import GstinError, check_digit, normalise_gstin
from tests.conftest import FakeDevice, build_catalogue

VALID_MH = "27AAPFU0939F1ZV"  # published sample GSTIN (Maharashtra)
VALID_KA = "29AAGCB7383J1Z4"


# ---------- the check digit ----------
@pytest.mark.parametrize("gstin", [VALID_MH, VALID_KA])
def test_check_digit_of_published_gstins(gstin):
    assert check_digit(gstin[:14]) == gstin[14]


def test_one_mistyped_character_is_caught():
    typo = VALID_MH[:7] + "8" + VALID_MH[8:]  # 0939 -> 0839
    with pytest.raises(GstinError, match="mistyped"):
        normalise_gstin(typo)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("27AAPFU0939F1Z", "15 characters"),
        ("27AAPFU0939F1XV", "not a GSTIN"),  # 14th char must be Z
        ("40AAPFU0939F1ZV", "state code"),
    ],
)
def test_wrong_gstins_say_why(raw, reason):
    with pytest.raises(GstinError, match=reason):
        normalise_gstin(raw)


def test_spaces_and_lower_case_are_tidied():
    assert normalise_gstin(" 27aapfu0939f1zv ") == VALID_MH


# ---------- the shop endpoint ----------
def test_regular_registration_derives_the_state_from_the_gstin(client, shop_a):
    h = shop_a.owner_h
    r = client.patch("/api/v1/shop", json={"gst_type": "regular", "gstin": VALID_MH}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["gst_type"] == "regular"
    assert r.json()["state_code"] == "27"  # was 33: the GSTIN decides


@pytest.mark.parametrize("gst_type", ["regular", "composition"])
def test_registered_shop_needs_a_gstin(client, shop_a, gst_type):
    h = shop_a.owner_h
    client.patch("/api/v1/shop", json={"gst_type": "unregistered", "gstin": None}, headers=h)
    r = client.patch("/api/v1/shop", json={"gst_type": gst_type}, headers=h)
    assert r.status_code == 422
    assert "GSTIN" in r.text
    assert client.get("/api/v1/shop", headers=h).json()["gst_type"] == "unregistered"


def test_unregistered_shop_can_drop_its_gstin(client, shop_a):
    h = shop_a.owner_h
    r = client.patch("/api/v1/shop", json={"gst_type": "unregistered", "gstin": None}, headers=h)
    assert r.status_code == 200 and r.json()["gstin"] is None


def test_gstin_then_type_in_two_steps_works(client, shop_a):
    h = shop_a.owner_h
    assert client.patch("/api/v1/shop", json={"gstin": VALID_KA}, headers=h).status_code == 200
    r = client.patch("/api/v1/shop", json={"gst_type": "composition"}, headers=h)
    assert r.status_code == 200 and r.json()["gstin"] == VALID_KA


def test_cannot_remove_the_gstin_of_a_registered_shop(client, shop_a):
    h = shop_a.owner_h
    client.patch("/api/v1/shop", json={"gst_type": "regular", "gstin": VALID_MH}, headers=h)
    r = client.patch("/api/v1/shop", json={"gstin": None}, headers=h)
    assert r.status_code == 422
    assert client.get("/api/v1/shop", headers=h).json()["gstin"] == VALID_MH


def test_mistyped_gstin_is_refused_by_the_api(client, shop_a):
    typo = VALID_MH[:7] + "8" + VALID_MH[8:]
    r = client.patch("/api/v1/shop", json={"gstin": typo}, headers=shop_a.owner_h)
    assert r.status_code == 422 and "mistyped" in r.text


def test_cashier_cannot_change_gst_settings(client, shop_a):
    r = client.patch("/api/v1/shop", json={"gst_type": "unregistered"}, headers=shop_a.cashier_h)
    assert r.status_code == 403


def test_devices_see_the_new_registration_in_the_catalogue(client, shop_a):
    h = shop_a.owner_h
    client.patch("/api/v1/shop", json={"gst_type": "regular", "gstin": VALID_MH}, headers=h)
    shop = client.get("/api/v1/catalogue", headers=shop_a.cashier_h).json()["shop"]
    assert (shop["gst_type"], shop["gstin"], shop["state_code"]) == ("regular", VALID_MH, "27")


# ---------- GST rate per item ----------
def test_item_gst_rate_must_be_a_current_slab(client, shop_a):
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    url = f"/api/v1/menu-items/{cat.tea['id']}"
    for bp in (1200, 2800, 50):  # old slabs and a typo
        r = client.patch(url, json={"gst_rate_bp": bp}, headers=h)
        assert r.status_code == 422, bp
    assert client.patch(url, json={"gst_rate_bp": 1800}, headers=h).json()["gst_rate_bp"] == 1800
    r = client.post(
        "/api/v1/menu-items",
        json={"name": "Lassi", "price_paise": 4000, "gst_rate_bp": 1200},
        headers=h,
    )
    assert r.status_code == 422


def test_a_40_percent_item_bills_and_syncs(client, shop_a):
    """40% is a slab the menu offers, so a bill with it must work end to end. The
    bill code still stopped at 28%, the old top slab: the till could not total
    the bill, the server refused it, and Shop & GST went blank (staging, 5 Oct
    2026, Badam milk set to 40%)."""
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    client.patch("/api/v1/shop", json={"gst_type": "regular", "gstin": VALID_MH}, headers=h)
    client.patch(f"/api/v1/menu-items/{cat.tea['id']}", json={"gst_rate_bp": 4000}, headers=h)
    device = FakeDevice(client, shop_a)
    bill = device.bill([("Masala tea", 1, [])])
    r = device.sync([bill])
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["status"] == "accepted" and res["totals_mismatch"] is False
    stored = client.get(f"/api/v1/bills/{bill['id']}", headers=h).json()
    # Rs 20 at 40% inclusive: 20 / 1.4 = 14.29, CGST = SGST = 20% of it = 2.86,
    # and the taxable value gives up a paise so the customer pays exactly 20.
    assert (stored["taxable_paise"], stored["cgst_paise"], stored["sgst_paise"]) == (
        1428,
        286,
        286,
    )
    assert stored["total_paise"] == 2000
