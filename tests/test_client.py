"""Tests for xero_blade_mcp.client — rate limiter, error classification, HTTP methods."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from xero_blade_mcp.auth import AuthError
from xero_blade_mcp.client import (
    ConflictError,
    ConnectionError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    XeroClient,
    XeroError,
    _classify_http_error,
    _RateLimiter,
)

from .conftest import make_response

# ===========================================================================
# Error classification
# ===========================================================================


class TestClassifyHttpError:
    def test_400_returns_validation_error(self) -> None:
        err = _classify_http_error(400, "Invalid field")
        assert isinstance(err, ValidationError)
        assert err.status_code == 400

    def test_404_returns_not_found_error(self) -> None:
        err = _classify_http_error(404, "Contact not found")
        assert isinstance(err, NotFoundError)
        assert err.status_code == 404

    def test_409_returns_conflict_error(self) -> None:
        err = _classify_http_error(409, "Concurrent modification")
        assert isinstance(err, ConflictError)
        assert err.status_code == 409

    def test_429_returns_rate_limit_error(self) -> None:
        err = _classify_http_error(429, "Too many requests")
        assert isinstance(err, RateLimitError)
        assert err.status_code == 429

    def test_500_returns_generic_error(self) -> None:
        err = _classify_http_error(500, "Internal server error")
        assert isinstance(err, XeroError)
        assert err.status_code == 500

    def test_empty_body_uses_status(self) -> None:
        err = _classify_http_error(503, "")
        assert "HTTP 503" in str(err)

    def test_long_body_truncated(self) -> None:
        long_body = "x" * 1000
        err = _classify_http_error(400, long_body)
        assert len(str(err)) < 600

    def test_scrubs_secrets_from_body(self) -> None:
        body = "Token: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
        err = _classify_http_error(401, body)
        assert "eyJ" not in str(err)


# ===========================================================================
# Rate limiter
# ===========================================================================


class TestRateLimiter:
    async def test_acquire_release(self) -> None:
        rl = _RateLimiter(calls_per_minute=60, max_concurrent=5)
        await rl.acquire()
        rl.release()

    async def test_concurrent_limit(self) -> None:
        rl = _RateLimiter(calls_per_minute=100, max_concurrent=2)

        acquired = 0

        async def try_acquire() -> None:
            nonlocal acquired
            await rl.acquire()
            acquired += 1
            await asyncio.sleep(0.05)
            rl.release()

        tasks = [asyncio.create_task(try_acquire()) for _ in range(4)]
        await asyncio.sleep(0.01)
        # Only 2 should have acquired at first
        assert acquired <= 2
        await asyncio.gather(*tasks)
        assert acquired == 4

    async def test_rate_limiting_cleans_timestamps(self) -> None:
        rl = _RateLimiter(calls_per_minute=60, max_concurrent=10)
        # Add some old timestamps
        rl._call_timestamps = [time.monotonic() - 120, time.monotonic() - 90]
        await rl.acquire()
        rl.release()
        # Old timestamps should be cleaned out
        assert len(rl._call_timestamps) == 1


# ===========================================================================
# XeroClient — request method
# ===========================================================================


def _make_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    response: AsyncMock | None = None,
) -> tuple[XeroClient, AsyncMock]:
    """Create a XeroClient with mocked auth and HTTP."""
    monkeypatch.setenv("XERO_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("XERO_TENANT_ID", "test-tenant")

    client = XeroClient()
    mock_http = AsyncMock()
    if response:
        mock_http.request.return_value = response
    client._http = mock_http
    return client, mock_http


class TestXeroClientRequest:
    async def test_success_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(200, json_data={"Contacts": [{"Name": "Acme"}]})
        client, mock_http = _make_mock_client(monkeypatch, resp)
        result = await client._request("GET", "https://api.xero.com/api.xro/2.0/Contacts")
        assert result == {"Contacts": [{"Name": "Acme"}]}

    async def test_204_returns_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(204)
        client, mock_http = _make_mock_client(monkeypatch, resp)
        result = await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")
        assert result == {}

    async def test_non_json_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(500, text="<html>Error</html>", content_type="text/html")
        client, _ = _make_mock_client(monkeypatch, resp)
        with pytest.raises(XeroError):
            await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")

    async def test_non_json_success_returns_raw(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(200, text="OK", content_type="text/plain")
        resp.json = MagicMock(side_effect=ValueError("not json"))
        client, _ = _make_mock_client(monkeypatch, resp)
        result = await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")
        assert "raw" in result

    async def test_connect_error_raises_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = _make_mock_client(monkeypatch)
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(ConnectionError, match="Connection refused"):
            await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")

    async def test_timeout_raises_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = _make_mock_client(monkeypatch)
        mock_http.request.side_effect = httpx.ReadTimeout("Read timed out")
        with pytest.raises(ConnectionError, match="timed out"):
            await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")

    async def test_generic_http_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = _make_mock_client(monkeypatch)
        mock_http.request.side_effect = httpx.HTTPError("Something broke")
        with pytest.raises(XeroError, match="Something broke"):
            await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")

    async def test_400_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(400, json_data={"Message": "Invalid"}, text="Invalid")
        client, _ = _make_mock_client(monkeypatch, resp)
        with pytest.raises(ValidationError):
            await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")

    async def test_404_raises_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(404, json_data={"Message": "Not found"}, text="Not found")
        client, _ = _make_mock_client(monkeypatch, resp)
        with pytest.raises(NotFoundError):
            await client._request("GET", "https://api.xero.com/api.xro/2.0/Test")

    async def test_params_filter_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(200, json_data={"ok": True})
        client, mock_http = _make_mock_client(monkeypatch, resp)
        await client._request("GET", "https://api.xero.com", params={"a": "1", "b": None})
        _, kwargs = mock_http.request.call_args
        assert kwargs["params"] == {"a": "1"}

    async def test_json_body_filter_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = make_response(200, json_data={"ok": True})
        client, mock_http = _make_mock_client(monkeypatch, resp)
        await client._request("POST", "https://api.xero.com", json_body={"Name": "Acme", "Email": None})
        _, kwargs = mock_http.request.call_args
        assert kwargs["json"] == {"Name": "Acme"}


# ===========================================================================
# XeroClient — 401 retry
# ===========================================================================


class TestXeroClient401Retry:
    async def test_retries_on_401_with_refresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("XERO_TENANT_ID", "t-1")

        resp_401 = make_response(401, text="Unauthorized")
        resp_200 = make_response(200, json_data={"ok": True})

        client = XeroClient()
        mock_http = AsyncMock()
        mock_http.request.side_effect = [resp_401, resp_200]
        client._http = mock_http

        # Mock the auth refresh and exchange to not actually call HTTP
        client._auth._refresh = AsyncMock(side_effect=AuthError("no refresh"))
        client._auth._client_credentials_exchange = AsyncMock()

        result = await client._request("GET", "https://api.xero.com/test")
        assert result == {"ok": True}
        assert mock_http.request.call_count == 2

    async def test_no_retry_on_401_when_retry_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp_401 = make_response(401, json_data={"Message": "Unauthorized"}, text="Unauthorized")
        client, _ = _make_mock_client(monkeypatch, resp_401)
        with pytest.raises(XeroError):
            await client._request("GET", "https://api.xero.com/test", retry_on_401=False)


# ===========================================================================
# XeroClient — 429 rate limit retry
# ===========================================================================


class TestXeroClient429Retry:
    async def test_retries_on_429(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("XERO_TENANT_ID", "t-1")

        resp_429 = make_response(429, text="Rate limited", headers={"Retry-After": "1"})
        resp_200 = make_response(200, json_data={"ok": True})

        client = XeroClient()
        mock_http = AsyncMock()
        mock_http.request.side_effect = [resp_429, resp_200]
        client._http = mock_http

        with patch("xero_blade_mcp.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await client._request("GET", "https://api.xero.com/test")
            mock_sleep.assert_called_once_with(1)
            assert result == {"ok": True}

    async def test_429_default_retry_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "test-token")
        monkeypatch.setenv("XERO_TENANT_ID", "t-1")

        resp_429 = make_response(429, text="Rate limited")
        resp_200 = make_response(200, json_data={"ok": True})

        client = XeroClient()
        mock_http = AsyncMock()
        mock_http.request.side_effect = [resp_429, resp_200]
        client._http = mock_http

        with patch("xero_blade_mcp.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._request("GET", "https://api.xero.com/test")
            mock_sleep.assert_called_once_with(5)  # Default Retry-After


# ===========================================================================
# XeroClient — Headers
# ===========================================================================


class TestXeroClientHeaders:
    async def test_headers_include_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "my-token")
        client = XeroClient()
        headers = await client._headers()
        assert headers["Authorization"] == "Bearer my-token"
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Xero-Client"] == "xero-blade-mcp"

    async def test_headers_include_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "my-token")
        monkeypatch.setenv("XERO_TENANT_ID", "tenant-abc")
        client = XeroClient()
        headers = await client._headers()
        assert headers["xero-tenant-id"] == "tenant-abc"

    async def test_headers_no_tenant_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "my-token")
        client = XeroClient()
        headers = await client._headers()
        assert "xero-tenant-id" not in headers


# ===========================================================================
# XeroClient — API method delegation
# ===========================================================================


class TestXeroClientAPIMethods:
    """Test that each client method calls the correct endpoint."""

    async def _setup_client(self, monkeypatch: pytest.MonkeyPatch) -> tuple[XeroClient, AsyncMock]:
        resp = make_response(200, json_data={"ok": True})
        return _make_mock_client(monkeypatch, resp)

    async def test_list_connections(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        mock_http.request.return_value = make_response(200, json_data=[{"tenantId": "t-1"}])
        result = await client.list_connections()
        assert result == [{"tenantId": "t-1"}]
        call_args = mock_http.request.call_args
        url = call_args.args[1]  # positional: (method, url)
        assert "connections" in url

    async def test_get_organisation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_organisation()
        url = mock_http.request.call_args[0][1]
        assert "Organisation" in url

    async def test_list_contacts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_contacts(where='Name=="Acme"', page=2)
        url = mock_http.request.call_args[0][1]
        assert "Contacts" in url
        params = mock_http.request.call_args[1]["params"]
        assert params["page"] == 2
        assert 'Name=="Acme"' in params["where"]

    async def test_get_contact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_contact("c-123")
        url = mock_http.request.call_args[0][1]
        assert "Contacts/c-123" in url

    async def test_create_contact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.create_contact({"Name": "Test"})
        method = mock_http.request.call_args[0][0]
        assert method == "POST"

    async def test_archive_contact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.archive_contact("c-123")
        body = mock_http.request.call_args[1]["json"]
        assert body["ContactStatus"] == "ARCHIVED"

    async def test_list_invoices_filters_sales(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_invoices()
        params = mock_http.request.call_args.kwargs["params"]
        assert 'Type=="ACCREC"' in params["where"]

    async def test_list_bills_filters_purchases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_bills()
        params = mock_http.request.call_args.kwargs["params"]
        assert 'Type=="ACCPAY"' in params["where"]

    async def test_create_invoice_sets_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.create_invoice({"Contact": {"ContactID": "c-1"}, "LineItems": []})
        method = mock_http.request.call_args.args[0]
        assert method == "PUT"
        body = mock_http.request.call_args.kwargs["json"]
        assert body["Type"] == "ACCREC"

    async def test_create_bill_sets_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.create_bill({"Contact": {"ContactID": "c-1"}, "LineItems": []})
        body = mock_http.request.call_args.kwargs["json"]
        assert body["Type"] == "ACCPAY"

    async def test_void_invoice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.void_invoice("inv-1")
        body = mock_http.request.call_args[1]["json"]
        assert body["Status"] == "VOIDED"

    async def test_delete_payment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.delete_payment("pay-1")
        body = mock_http.request.call_args[1]["json"]
        assert body["Status"] == "DELETED"

    async def test_list_employees_uses_payroll_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_employees()
        url = mock_http.request.call_args[0][1]
        assert "payroll.xro" in url

    async def test_list_bank_transactions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_bank_transactions(where='Status=="AUTHORISED"', page=3)
        url = mock_http.request.call_args[0][1]
        assert "BankTransactions" in url

    async def test_list_payments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_payments(page=2)
        url = mock_http.request.call_args[0][1]
        assert "Payments" in url

    async def test_list_credit_notes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_credit_notes()
        url = mock_http.request.call_args[0][1]
        assert "CreditNotes" in url

    async def test_list_purchase_orders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_purchase_orders()
        url = mock_http.request.call_args[0][1]
        assert "PurchaseOrders" in url

    async def test_list_quotes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_quotes()
        url = mock_http.request.call_args[0][1]
        assert "Quotes" in url

    async def test_list_accounts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_accounts(where='Type=="REVENUE"')
        url = mock_http.request.call_args[0][1]
        assert "Accounts" in url

    async def test_list_manual_journals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_manual_journals()
        url = mock_http.request.call_args[0][1]
        assert "ManualJournals" in url

    async def test_get_profit_and_loss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_profit_and_loss(from_date="2026-01-01", to_date="2026-03-31")
        url = mock_http.request.call_args[0][1]
        assert "ProfitAndLoss" in url

    async def test_get_balance_sheet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_balance_sheet(date="2026-03-31")
        url = mock_http.request.call_args[0][1]
        assert "BalanceSheet" in url

    async def test_get_trial_balance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_trial_balance()
        url = mock_http.request.call_args[0][1]
        assert "TrialBalance" in url

    async def test_get_aged_receivables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_aged_receivables()
        url = mock_http.request.call_args[0][1]
        assert "AgedReceivablesByContact" in url

    async def test_get_aged_payables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_aged_payables()
        url = mock_http.request.call_args[0][1]
        assert "AgedPayablesByContact" in url

    async def test_list_tax_rates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_tax_rates()
        url = mock_http.request.call_args[0][1]
        assert "TaxRates" in url

    async def test_list_currencies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_currencies()
        url = mock_http.request.call_args[0][1]
        assert "Currencies" in url

    async def test_list_tracking_categories(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_tracking_categories()
        url = mock_http.request.call_args[0][1]
        assert "TrackingCategories" in url

    async def test_list_branding_themes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_branding_themes()
        url = mock_http.request.call_args[0][1]
        assert "BrandingThemes" in url

    async def test_list_timesheets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_timesheets()
        url = mock_http.request.call_args[0][1]
        assert "payroll.xro" in url
        assert "Timesheets" in url

    async def test_approve_timesheet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.approve_timesheet("ts-1")
        url = mock_http.request.call_args[0][1]
        assert "Timesheets/ts-1/Approve" in url

    async def test_list_payslips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.list_payslips("pr-1")
        url = mock_http.request.call_args[0][1]
        assert "PayRuns/pr-1" in url

    async def test_get_payslip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, mock_http = await self._setup_client(monkeypatch)
        await client.get_payslip("ps-1")
        url = mock_http.request.call_args[0][1]
        assert "Payslip/ps-1" in url


# ===========================================================================
# XeroClient — Close
# ===========================================================================


class TestXeroClientClose:
    async def test_close_both_clients(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "tok")
        client = XeroClient()
        mock_http = AsyncMock()
        client._http = mock_http
        client._auth._http = AsyncMock()
        await client.close()
        mock_http.aclose.assert_called_once()
        client._auth._http.aclose.assert_called_once()

    async def test_close_without_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "tok")
        client = XeroClient()
        await client.close()  # Should not raise


# ===========================================================================
# XeroClient — get_invoice_pdf
# ===========================================================================


class TestXeroClientPDF:
    async def test_pdf_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("XERO_TENANT_ID", "t-1")

        mock_resp = AsyncMock()
        mock_resp.is_success = True
        mock_resp.content = b"%PDF-1.4 fake pdf content here"
        mock_resp.status_code = 200

        client = XeroClient()
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        client._http = mock_http

        result = await client.get_invoice_pdf("inv-1")
        assert result["content_type"] == "application/pdf"
        assert result["size_bytes"] > 0

    async def test_pdf_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("XERO_TENANT_ID", "t-1")

        mock_resp = AsyncMock()
        mock_resp.is_success = False
        mock_resp.status_code = 404

        client = XeroClient()
        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        client._http = mock_http

        with pytest.raises(XeroError, match="PDF download failed"):
            await client.get_invoice_pdf("inv-1")
