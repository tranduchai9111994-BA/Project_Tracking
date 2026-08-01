"""Tests session login + auth_store (hashed passwords, default admin)."""
from __future__ import annotations

import json
import os

import pytest
from werkzeug.security import check_password_hash

from analyzer import auth_store


# ==========================================================================
# Unit — auth_store
# ==========================================================================

class TestAuthStore:
    def test_ensure_default_admin_creates_hashed(self, tmp_path):
        path = str(tmp_path / "users.json")
        created = auth_store.ensure_default_admin(path)
        assert created is True
        # Lần 2 không tạo lại
        assert auth_store.ensure_default_admin(path) is False

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        users = data["users"]
        assert len(users) == 1
        assert users[0]["username"] == "admin"
        assert users[0]["role"] == "admin"
        pw_hash = users[0]["password_hash"]
        assert pw_hash
        assert pw_hash != "admin"
        assert "admin" not in pw_hash  # không lưu plaintext
        assert check_password_hash(pw_hash, "admin")

    def test_authenticate_success_and_fail(self, tmp_path):
        path = str(tmp_path / "users.json")
        auth_store.ensure_default_admin(path)
        ok = auth_store.authenticate("admin", "admin", path=path)
        assert ok is not None
        assert ok["username"] == "admin"
        assert "password_hash" not in ok

        assert auth_store.authenticate("admin", "wrong", path=path) is None
        assert auth_store.authenticate("nobody", "admin", path=path) is None

    def test_create_user_and_change_password(self, tmp_path):
        path = str(tmp_path / "users.json")
        auth_store.ensure_default_admin(path)
        u = auth_store.create_user("viewer1", "secret1", role="viewer", path=path)
        assert u["username"] == "viewer1"
        assert u["role"] == "viewer"

        assert auth_store.authenticate("viewer1", "secret1", path=path)
        auth_store.change_password(
            u["id"], "secret2", path=path,
            current_password="secret1", require_current=True,
        )
        assert auth_store.authenticate("viewer1", "secret1", path=path) is None
        assert auth_store.authenticate("viewer1", "secret2", path=path)

        with pytest.raises(auth_store.AuthError):
            auth_store.create_user("viewer1", "x", path=path)


# ==========================================================================
# HTTP — login gate
# ==========================================================================

class TestAuthHttp:
    def test_login_success(self, flask_client_anon):
        r = flask_client_anon.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"

        me = flask_client_anon.get("/api/auth/me")
        assert me.status_code == 200
        assert me.get_json()["user"]["username"] == "admin"

    def test_login_fail(self, flask_client_anon):
        r = flask_client_anon.post(
            "/api/auth/login",
            json={"username": "admin", "password": "bad"},
        )
        assert r.status_code == 401
        assert r.get_json()["code"] == "AUTH_FAILED"

    def test_api_requires_login(self, flask_client_anon):
        r = flask_client_anon.get("/api/projects")
        assert r.status_code == 401
        assert r.get_json()["code"] == "AUTH_REQUIRED"

    def test_index_redirects_when_anon(self, flask_client_anon):
        r = flask_client_anon.get("/", follow_redirects=False)
        assert r.status_code in (302, 303)
        assert "/login" in (r.headers.get("Location") or "")

    def test_health_and_login_page_public(self, flask_client_anon):
        assert flask_client_anon.get("/api/health").status_code == 200
        page = flask_client_anon.get("/login")
        assert page.status_code == 200
        assert "Đăng nhập".encode("utf-8") in page.data

    def test_password_stored_hashed_after_login_flow(self, flask_client_anon, auth_users_file):
        flask_client_anon.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        raw = open(auth_users_file, encoding="utf-8").read()
        assert '"password": "admin"' not in raw
        assert "password_hash" in raw
        h = auth_store.password_hash_for_username("admin", path=auth_users_file)
        assert h and check_password_hash(h, "admin")

    def test_admin_create_user(self, flask_client):
        r = flask_client.post(
            "/api/auth/users",
            json={"username": "ba1", "password": "ba-pass", "role": "viewer"},
        )
        assert r.status_code == 201
        users = flask_client.get("/api/auth/users").get_json()["users"]
        assert any(u["username"] == "ba1" for u in users)

    def test_logout(self, flask_client):
        r = flask_client.post("/api/auth/logout")
        assert r.status_code == 200
        assert flask_client.get("/api/projects").status_code == 401
