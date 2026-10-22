"""Dish photos taken on the owner's phone (README, "9.17")."""

import base64

from tests.conftest import build_catalogue

API = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _upload(client, shop, data, who="owner_h"):
    return client.post(
        f"{API}/menu-photos", json={"base64": _b64(data)}, headers=getattr(shop, who)
    )


def test_an_uploaded_photo_is_served_to_anyone_as_a_picture_only(client, shop_a):
    r = _upload(client, shop_a, JPEG)
    assert r.status_code == 201, r.text
    url = r.json()["photo_url"]
    assert url.startswith("/dish-photos/") and len(url) == len("/dish-photos/") + 32
    got = client.get(f"{API}/public{url}")  # no login: it is on a public menu
    assert got.status_code == 200 and got.content == JPEG
    assert got.headers["content-type"] == "image/jpeg"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in got.headers["content-security-policy"]
    assert "immutable" in got.headers["cache-control"]


def test_the_picture_type_comes_from_the_bytes_not_from_the_sender(client, shop_a):
    html = _upload(client, shop_a, b"<html><script>alert(1)</script></html>")
    assert html.status_code == 422 and html.json()["detail"]["code"] == "bad_photo"
    assert _upload(client, shop_a, PNG).status_code == 201
    not_base64 = client.post(f"{API}/menu-photos", json={"base64": "***"}, headers=shop_a.owner_h)
    assert not_base64.status_code == 422


def test_a_huge_picture_is_refused(client, shop_a):
    r = _upload(client, shop_a, JPEG + b"\x00" * 410_000)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "photo_too_big"


def test_only_the_owner_uploads(client, shop_a):
    assert _upload(client, shop_a, JPEG, who="cashier_h").status_code == 403
    assert client.post(f"{API}/menu-photos", json={"base64": _b64(JPEG)}).status_code in (401, 403)


def test_a_dish_can_carry_an_uploaded_photo_and_no_other_path(client, shop_a):
    cat = build_catalogue(client, shop_a)
    url = _upload(client, shop_a, JPEG).json()["photo_url"]
    ok = client.patch(
        f"{API}/menu-items/{cat.tea['id']}", json={"photo_url": url}, headers=shop_a.owner_h
    )
    assert ok.status_code == 200 and ok.json()["photo_url"] == url
    for bad in (
        "/dish-photos/../../etc/passwd",
        "/dish-photos/xyz",
        "/other/path",
        "data:image/png;base64,AA",
    ):
        r = client.patch(
            f"{API}/menu-items/{cat.tea['id']}", json={"photo_url": bad}, headers=shop_a.owner_h
        )
        assert r.status_code == 422, bad


def test_a_missing_or_malformed_photo_id_is_a_404(client):
    assert client.get(f"{API}/public/dish-photos/{'0' * 32}").status_code == 404
    assert client.get(f"{API}/public/dish-photos/not-an-id").status_code == 404
