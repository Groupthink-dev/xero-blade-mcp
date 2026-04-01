"""Tests for xero_blade_mcp.auth — TokenStore, XeroAuth modes, error paths."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from xero_blade_mcp.auth import (
    REFRESH_MARGIN_SECONDS,
    AuthError,
    TokenStore,
    XeroAuth,
)


@pytest.fixture(autouse=True)
def _no_real_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent tests from reading/writing the real token file."""
    monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_DIR", tmp_path / "xero-tokens")
    monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", tmp_path / "xero-tokens" / "tokens.json")


# ===========================================================================
# TokenStore
# ===========================================================================


class TestTokenStore:
    def test_initial_state_expired(self) -> None:
        store = TokenStore()
        assert store.access_token is None
        assert store.tenant_id is None
        assert store.is_expired() is True
        assert store.has_refresh_token() is False

    def test_update_sets_access_token(self) -> None:
        store = TokenStore()
        store.update({"access_token": "tok123", "expires_in": 1800})
        assert store.access_token == "tok123"

    def test_update_preserves_existing_refresh_token(self) -> None:
        store = TokenStore()
        store._refresh_token = "old-refresh"
        store.update({"access_token": "tok123"})
        assert store._refresh_token == "old-refresh"

    def test_update_overwrites_refresh_token(self) -> None:
        store = TokenStore()
        store._refresh_token = "old-refresh"
        store.update({"access_token": "tok123", "refresh_token": "new-refresh"})
        assert store._refresh_token == "new-refresh"

    def test_is_expired_within_margin(self) -> None:
        store = TokenStore()
        store._access_token = "tok"
        store._expires_at = time.time() + REFRESH_MARGIN_SECONDS - 1
        assert store.is_expired() is True

    def test_is_expired_outside_margin(self) -> None:
        store = TokenStore()
        store._access_token = "tok"
        store._expires_at = time.time() + REFRESH_MARGIN_SECONDS + 60
        assert store.is_expired() is False

    def test_has_refresh_token_true(self) -> None:
        store = TokenStore()
        store._refresh_token = "refresh-tok"
        assert store.has_refresh_token() is True

    def test_has_refresh_token_false_empty(self) -> None:
        store = TokenStore()
        store._refresh_token = ""
        assert store.has_refresh_token() is False

    def test_tenant_id_property(self) -> None:
        store = TokenStore()
        store.tenant_id = "tenant-123"
        assert store.tenant_id == "tenant-123"

    def test_save_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_DIR", tmp_path)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", tmp_path / "tokens.json")

        store = TokenStore()
        store.update({"access_token": "tok", "refresh_token": "ref", "expires_in": 1800})

        token_file = tmp_path / "tokens.json"
        assert token_file.exists()
        data = json.loads(token_file.read_text())
        assert data["access_token"] == "tok"
        assert data["refresh_token"] == "ref"
        assert data["expires_at"] > time.time()

    def test_save_sets_permissions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_DIR", tmp_path)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", tmp_path / "tokens.json")

        store = TokenStore()
        store.update({"access_token": "tok", "refresh_token": "ref"})

        token_file = tmp_path / "tokens.json"
        assert oct(token_file.stat().st_mode)[-3:] == "600"

    def test_no_file_written_without_refresh_token(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client-credentials tokens (no refresh_token) stay in memory only."""
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_DIR", tmp_path)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", tmp_path / "tokens.json")

        store = TokenStore()
        store.update({"access_token": "tok", "expires_in": 1800})

        assert not (tmp_path / "tokens.json").exists()
        assert store.access_token == "tok"

    def test_load_returns_true_with_valid_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        token_file = tmp_path / "tokens.json"
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", token_file)

        data = {
            "access_token": "loaded-tok",
            "refresh_token": "loaded-ref",
            "expires_at": time.time() + 3600,
            "tenant_id": "t-123",
        }
        token_file.write_text(json.dumps(data))

        store = TokenStore()
        assert store.load() is True
        assert store.access_token == "loaded-tok"
        assert store._refresh_token == "loaded-ref"
        assert store.tenant_id == "t-123"

    def test_load_returns_false_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", tmp_path / "nonexistent.json")
        store = TokenStore()
        assert store.load() is False

    def test_load_returns_false_invalid_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        token_file = tmp_path / "tokens.json"
        token_file.write_text("not valid json{{{")
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", token_file)

        store = TokenStore()
        assert store.load() is False

    def test_load_returns_false_empty_token(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        token_file = tmp_path / "tokens.json"
        token_file.write_text(json.dumps({"access_token": None}))
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", token_file)

        store = TokenStore()
        assert store.load() is False

    def test_update_default_expires_in(self) -> None:
        """Xero default is 30 min = 1800s when not specified."""
        store = TokenStore()
        before = time.time()
        store.update({"access_token": "tok"})
        after = time.time()
        assert before + 1800 <= store._expires_at <= after + 1800


# ===========================================================================
# XeroAuth — Static token mode
# ===========================================================================


class TestXeroAuthStaticToken:
    async def test_returns_static_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "static-tok-123")
        auth = XeroAuth()
        token = await auth.get_access_token()
        assert token == "static-tok-123"

    async def test_static_token_priority_over_client_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "static-tok")
        monkeypatch.setenv("XERO_CLIENT_ID", "client-id")
        monkeypatch.setenv("XERO_CLIENT_SECRET", "client-secret")
        auth = XeroAuth()
        token = await auth.get_access_token()
        assert token == "static-tok"

    async def test_static_token_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "  tok-with-spaces  ")
        auth = XeroAuth()
        token = await auth.get_access_token()
        assert token == "tok-with-spaces"


# ===========================================================================
# XeroAuth — Client credentials mode
# ===========================================================================


class TestXeroAuthClientCredentials:
    async def test_exchanges_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_CLIENT_ID", "cid")
        monkeypatch.setenv("XERO_CLIENT_SECRET", "csec")

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "cc-token", "expires_in": 1800}

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        auth = XeroAuth()
        auth._http = mock_http

        token = await auth.get_access_token()
        assert token == "cc-token"
        mock_http.post.assert_called_once()

    async def test_reuses_valid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_CLIENT_ID", "cid")
        monkeypatch.setenv("XERO_CLIENT_SECRET", "csec")

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"access_token": "cc-token", "expires_in": 1800}

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        auth = XeroAuth()
        auth._http = mock_http

        await auth.get_access_token()
        await auth.get_access_token()
        # Should only call post once since token is still valid
        assert mock_http.post.call_count == 1

    async def test_exchange_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_CLIENT_ID", "cid")
        monkeypatch.setenv("XERO_CLIENT_SECRET", "csec")

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 401
        mock_response.text = "invalid_client"

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        auth = XeroAuth()
        auth._http = mock_http

        with pytest.raises(AuthError, match="Token exchange failed"):
            await auth.get_access_token()

    async def test_exchange_http_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_CLIENT_ID", "cid")
        monkeypatch.setenv("XERO_CLIENT_SECRET", "csec")

        mock_http = AsyncMock()
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")

        auth = XeroAuth()
        auth._http = mock_http

        with pytest.raises(AuthError, match="Token exchange failed"):
            await auth.get_access_token()


# ===========================================================================
# XeroAuth — Refresh token mode
# ===========================================================================


class TestXeroAuthRefreshToken:
    async def test_refresh_token_flow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_CLIENT_ID", "cid")
        token_dir = tmp_path / "xero-refresh"
        token_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_DIR", token_dir)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", token_dir / "tokens.json")

        # Pre-seed an expired token with a refresh token
        token_file = token_dir / "tokens.json"
        token_file.write_text(
            json.dumps(
                {
                    "access_token": "expired-tok",
                    "refresh_token": "valid-refresh",
                    "expires_at": time.time() - 100,
                    "tenant_id": "t-1",
                }
            )
        )

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "access_token": "new-tok",
            "refresh_token": "new-refresh",
            "expires_in": 1800,
        }

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        auth = XeroAuth()
        auth._http = mock_http

        token = await auth.get_access_token()
        assert token == "new-tok"

    async def test_refresh_failure_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_CLIENT_ID", "cid")
        token_dir = tmp_path / "xero-refresh-fail"
        token_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_DIR", token_dir)
        monkeypatch.setattr("xero_blade_mcp.auth.TOKEN_FILE", token_dir / "tokens.json")

        token_file = token_dir / "tokens.json"
        token_file.write_text(
            json.dumps(
                {
                    "access_token": "expired-tok",
                    "refresh_token": "invalid-refresh",
                    "expires_at": time.time() - 100,
                }
            )
        )

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        auth = XeroAuth()
        auth._http = mock_http

        with pytest.raises(AuthError, match="Token refresh failed"):
            await auth.get_access_token()

    async def test_refresh_requires_client_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No client ID set, no static token, no client credentials
        auth = XeroAuth()
        auth._store._access_token = "expired"
        auth._store._refresh_token = "refresh"
        auth._store._expires_at = time.time() - 100

        with pytest.raises(AuthError, match="XERO_CLIENT_ID required"):
            await auth._refresh()


# ===========================================================================
# XeroAuth — No credentials
# ===========================================================================


class TestXeroAuthNoCredentials:
    async def test_no_creds_raises(self) -> None:
        auth = XeroAuth()
        with pytest.raises(AuthError, match="No valid Xero credentials"):
            await auth.get_access_token()

    async def test_no_creds_lists_options(self) -> None:
        auth = XeroAuth()
        with pytest.raises(AuthError) as exc_info:
            await auth.get_access_token()
        msg = str(exc_info.value)
        assert "XERO_CLIENT_ID" in msg
        assert "XERO_ACCESS_TOKEN" in msg
        assert "PKCE" in msg


# ===========================================================================
# XeroAuth — Tenant ID
# ===========================================================================


class TestXeroAuthTenantId:
    def test_env_tenant_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_TENANT_ID", "env-tenant")
        auth = XeroAuth()
        assert auth.get_tenant_id() == "env-tenant"

    def test_store_tenant_id(self) -> None:
        auth = XeroAuth()
        auth.set_tenant_id("store-tenant")
        assert auth.get_tenant_id() == "store-tenant"

    def test_env_overrides_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_TENANT_ID", "env-tenant")
        auth = XeroAuth()
        auth.set_tenant_id("store-tenant")
        assert auth.get_tenant_id() == "env-tenant"

    def test_no_tenant_id(self) -> None:
        auth = XeroAuth()
        assert auth.get_tenant_id() is None


# ===========================================================================
# XeroAuth — Close
# ===========================================================================


class TestXeroAuthClose:
    async def test_close_with_http_client(self) -> None:
        auth = XeroAuth()
        mock_http = AsyncMock()
        auth._http = mock_http
        await auth.close()
        mock_http.aclose.assert_called_once()

    async def test_close_without_http_client(self) -> None:
        auth = XeroAuth()
        await auth.close()  # Should not raise
