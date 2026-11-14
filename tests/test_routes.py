from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from finance import auth, db

PAGES = [
    "/",
    "/transactions",
    "/accounts",
    "/categories",
    "/rules",
    "/summary",
    "/chart",
    "/import",
]


@pytest.fixture
def client(tmp_db, auth_env, monkeypatch):
    """App client on an empty DB, with no password configured (open mode)."""
    monkeypatch.delenv("FINANCE_PASSWORD_HASH", raising=False)
    from finance import main

    # https base URL so the `secure` session cookie is sent back by the client.
    with TestClient(main.app, base_url="https://testserver", follow_redirects=False) as c:
        yield c


@pytest.fixture
def locked_client(client, monkeypatch):
    """Same client, but with a password set so the auth middleware is active."""
    monkeypatch.setenv("FINANCE_PASSWORD_HASH", auth.hash_password("s3cret-pw"))
    return client


@pytest.mark.parametrize("path", ["/login", "/healthz", *PAGES])
def test_pages_render_on_empty_db(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/master-plan", "/graf", "/no-such-page"])
def test_unknown_pages_404(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", PAGES)
def test_pages_require_login_when_password_set(locked_client, path):
    resp = locked_client.get(path)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_public_paths_stay_open_when_password_set(locked_client):
    assert locked_client.get("/login").status_code == 200
    assert locked_client.get("/healthz").status_code == 200


def test_login_rejects_wrong_password(locked_client):
    resp = locked_client.post("/login", data={"password": "nope"})
    assert resp.status_code == 401
    assert "Incorrect password." in resp.text
    assert locked_client.get("/").status_code == 303


def test_login_then_access_then_logout(locked_client):
    resp = locked_client.post("/login", data={"password": "s3cret-pw"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert locked_client.get("/").status_code == 200

    assert locked_client.get("/logout").status_code == 303
    assert locked_client.get("/").status_code == 303


def test_forged_session_cookie_is_rejected(locked_client):
    locked_client.cookies.set(auth.SESSION_COOKIE_NAME, "forged.token.value")
    assert locked_client.get("/").status_code == 303


def test_add_category_shows_up(client):
    resp = client.post("/categories/add", data={"name": "Coffee", "kind": "expense"})
    assert resp.status_code == 303
    assert "Coffee" in {c["name"] for c in db.list_categories()}
    assert "Coffee" in client.get("/categories").text


def test_sidebar_month_cookie_accepts_only_valid_values(client):
    ok = client.post("/sb-month", data={"month": "2026-03", "next": "/chart"})
    assert ok.status_code == 303
    assert ok.headers["location"] == "/chart"
    assert "sb_month=2026-03" in ok.headers.get("set-cookie", "")

    bad = client.post("/sb-month", data={"month": "garbage", "next": "https://evil.example"})
    assert bad.headers["location"] == "/"
    assert "set-cookie" not in bad.headers


def test_stale_sidebar_month_cookie_does_not_break_pages(client):
    # Old installs may still carry the removed "master-plan" period in the cookie.
    client.cookies.set("sb_month", "master-plan")
    assert client.get("/").status_code == 200
