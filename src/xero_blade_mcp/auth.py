"""Xero OAuth2 authentication — Custom Connection and PKCE support.

Handles token acquisition, storage, and automatic refresh for the Xero API.

Supported auth modes (in priority order):
1. XERO_ACCESS_TOKEN — pre-obtained token (testing, short-lived)
2. XERO_CLIENT_ID + XERO_CLIENT_SECRET — Custom Connection (M2M, recommended)
3. Token file — previously obtained tokens at ~/.xero-blade-mcp/tokens.json
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from xero_blade_mcp.models import TOKEN_URL, scrub_secrets

logger = logging.getLogger(__name__)

TOKEN_DIR = Path.home() / ".xero-blade-mcp"
TOKEN_FILE = TOKEN_DIR / "tokens.json"
REFRESH_MARGIN_SECONDS = 120  # Refresh 2 minutes before expiry


class AuthError(Exception):
    """Authentication configuration or token error."""


class TokenStore:
    """Manages OAuth2 token persistence and refresh."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._tenant_id: str | None = None

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def tenant_id(self) -> str | None:
        return self._tenant_id

    @tenant_id.setter
    def tenant_id(self, value: str | None) -> None:
        self._tenant_id = value

    def is_expired(self) -> bool:
        """Check if the access token has expired or is about to."""
        if not self._access_token:
            return True
        return time.time() >= (self._expires_at - REFRESH_MARGIN_SECONDS)

    def has_refresh_token(self) -> bool:
        return bool(self._refresh_token)

    def update(self, token_response: dict[str, Any]) -> None:
        """Update tokens from an OAuth2 token response."""
        self._access_token = token_response["access_token"]
        self._refresh_token = token_response.get("refresh_token", self._refresh_token)
        expires_in = token_response.get("expires_in", 1800)  # Xero default: 30 min
        self._expires_at = time.time() + expires_in
        self._save()

    def _save(self) -> None:
        """Persist tokens to disk."""
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
            "tenant_id": self._tenant_id,
        }
        TOKEN_FILE.write_text(json.dumps(data, indent=2))
        TOKEN_FILE.chmod(0o600)  # Owner read/write only

    def load(self) -> bool:
        """Load tokens from disk. Returns True if valid tokens were loaded."""
        if not TOKEN_FILE.exists():
            return False
        try:
            data = json.loads(TOKEN_FILE.read_text())
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._expires_at = data.get("expires_at", 0.0)
            self._tenant_id = data.get("tenant_id")
            return bool(self._access_token)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load token file: %s", e)
            return False


class XeroAuth:
    """Manages Xero OAuth2 authentication lifecycle.

    Priority:
    1. XERO_ACCESS_TOKEN env var (static token, no refresh)
    2. XERO_CLIENT_ID + XERO_CLIENT_SECRET (Custom Connection — auto token exchange)
    3. Stored token file with refresh
    """

    def __init__(self) -> None:
        self._store = TokenStore()
        self._client_id = os.environ.get("XERO_CLIENT_ID", "").strip()
        self._client_secret = os.environ.get("XERO_CLIENT_SECRET", "").strip()
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        # Mode 1: Static access token
        static_token = os.environ.get("XERO_ACCESS_TOKEN", "").strip()
        if static_token:
            return static_token

        # Mode 2: Client credentials (Custom Connection)
        if self._client_id and self._client_secret:
            if self._store.is_expired():
                await self._client_credentials_exchange()
            token = self._store.access_token
            if token:
                return token
            raise AuthError("Client credentials exchange failed — no access token returned.")

        # Mode 3: Stored token with refresh
        if not self._store.access_token:
            self._store.load()

        if self._store.is_expired() and self._store.has_refresh_token():
            await self._refresh()

        token = self._store.access_token
        if token and not self._store.is_expired():
            return token

        raise AuthError(
            "No valid Xero credentials. Configure one of:\n"
            "  1. XERO_CLIENT_ID + XERO_CLIENT_SECRET (Custom Connection — recommended)\n"
            "  2. XERO_ACCESS_TOKEN (pre-obtained token)\n"
            "  3. Run OAuth2 PKCE flow to obtain tokens"
        )

    def get_tenant_id(self) -> str | None:
        """Return the configured tenant ID."""
        env_tenant = os.environ.get("XERO_TENANT_ID", "").strip()
        if env_tenant:
            return env_tenant
        return self._store.tenant_id

    def set_tenant_id(self, tenant_id: str) -> None:
        """Set the active tenant ID."""
        self._store.tenant_id = tenant_id

    async def _client_credentials_exchange(self) -> None:
        """Exchange client credentials for an access token (Custom Connection)."""
        http = await self._get_http()
        try:
            response = await http.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            if not response.is_success:
                body = response.text
                raise AuthError(f"Token exchange failed (HTTP {response.status_code}): {scrub_secrets(body)}")

            self._store.update(response.json())
            logger.info("Xero token obtained via client credentials")
        except httpx.HTTPError as e:
            raise AuthError(f"Token exchange failed: {scrub_secrets(str(e))}") from e

    async def _refresh(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self._client_id:
            raise AuthError("XERO_CLIENT_ID required for token refresh")

        http = await self._get_http()
        try:
            data: dict[str, str] = {
                "grant_type": "refresh_token",
                "refresh_token": self._store._refresh_token or "",
                "client_id": self._client_id,
            }
            if self._client_secret:
                data["client_secret"] = self._client_secret

            response = await http.post(TOKEN_URL, data=data)
            if not response.is_success:
                body = response.text
                raise AuthError(f"Token refresh failed (HTTP {response.status_code}): {scrub_secrets(body)}")

            self._store.update(response.json())
            logger.info("Xero token refreshed")
        except httpx.HTTPError as e:
            raise AuthError(f"Token refresh failed: {scrub_secrets(str(e))}") from e

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()
