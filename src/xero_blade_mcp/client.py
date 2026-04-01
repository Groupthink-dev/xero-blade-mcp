"""Xero API client.

Async wrapper over ``httpx.AsyncClient`` with typed exceptions,
rate limit handling, multi-tenant support, credential scrubbing,
and automatic token refresh. No SDK dependency — direct REST API
calls for full control over response shaping.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from xero_blade_mcp.auth import AuthError, XeroAuth
from xero_blade_mcp.models import (
    ACCOUNTING_API_URL,
    IDENTITY_API_URL,
    INVOICE_TYPE_BILL,
    INVOICE_TYPE_SALES,
    PAYROLL_AU_API_URL,
    scrub_secrets,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class XeroError(Exception):
    """Base exception for Xero client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NotFoundError(XeroError):
    """Requested resource not found."""


class RateLimitError(XeroError):
    """Rate limit exceeded — back off and retry."""


class ValidationError(XeroError):
    """Request validation failed — invalid parameters."""


class ConflictError(XeroError):
    """Conflict — e.g., concurrent modification."""


class ConnectionError(XeroError):  # noqa: A001
    """Cannot connect to Xero API."""


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

_STATUS_TO_ERROR: dict[int, type[XeroError]] = {
    400: ValidationError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def _classify_http_error(status_code: int, body: str) -> XeroError:
    """Map HTTP status code and response body to a typed exception."""
    message = scrub_secrets(body[:500] if body else f"HTTP {status_code}")
    exc_cls = _STATUS_TO_ERROR.get(status_code, XeroError)
    return exc_cls(message, status_code=status_code)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Token bucket rate limiter for Xero API (60 calls/min, 5 concurrent)."""

    def __init__(self, calls_per_minute: int = 60, max_concurrent: int = 5) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._calls_per_minute = calls_per_minute
        self._call_timestamps: list[float] = []

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        await self._semaphore.acquire()

        now = time.monotonic()
        cutoff = now - 60.0
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]

        if len(self._call_timestamps) >= self._calls_per_minute:
            oldest = self._call_timestamps[0]
            wait = 60.0 - (now - oldest) + 0.1
            if wait > 0:
                logger.info("Rate limit: waiting %.1fs", wait)
                await asyncio.sleep(wait)

        self._call_timestamps.append(time.monotonic())

    def release(self) -> None:
        """Release the concurrency slot."""
        self._semaphore.release()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class XeroClient:
    """Async Xero API client with rate limiting and auto-refresh.

    Supports both Accounting and Payroll AU APIs. Multi-tenant via
    xero-tenant-id header.
    """

    def __init__(self) -> None:
        self._auth = XeroAuth()
        self._rate_limiter = _RateLimiter()
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def _headers(self) -> dict[str, str]:
        """Build request headers with auth and tenant."""
        token = await self._auth.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Xero-Client": "xero-blade-mcp",
            "X-Xero-Client-Version": "0.1.0",
        }
        tenant_id = self._auth.get_tenant_id()
        if tenant_id:
            headers["xero-tenant-id"] = tenant_id
        return headers

    # ------------------------------------------------------------------
    # Core HTTP methods
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        """Execute an HTTP request with rate limiting, auth refresh, and error handling."""
        await self._rate_limiter.acquire()
        try:
            http = await self._get_http()
            headers = await self._headers()

            try:
                response = await http.request(
                    method,
                    url,
                    headers=headers,
                    params={k: v for k, v in (params or {}).items() if v is not None} if params else None,
                    json={k: v for k, v in json_body.items() if v is not None} if json_body else None,
                )
            except httpx.ConnectError as e:
                raise ConnectionError(scrub_secrets(str(e))) from e
            except httpx.TimeoutException as e:
                raise ConnectionError(f"Request timed out: {scrub_secrets(str(e))}") from e
            except httpx.HTTPError as e:
                raise XeroError(scrub_secrets(str(e))) from e

            # Handle 401 with token refresh
            if response.status_code == 401 and retry_on_401:
                try:
                    await self._auth._refresh()
                except AuthError:
                    await self._auth._client_credentials_exchange()
                return await self._request(method, url, params, json_body, retry_on_401=False)

            # Handle 429 with retry-after
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                logger.warning("Rate limited, retrying after %ds", retry_after)
                await asyncio.sleep(retry_after)
                return await self._request(method, url, params, json_body, retry_on_401=False)

            if response.status_code == 204:
                return {}

            # Xero returns XML for some error responses
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type and not response.is_success:
                raise _classify_http_error(response.status_code, response.text)

            try:
                body = response.json()
            except ValueError:
                if response.is_success:
                    return {"raw": response.text}
                raise XeroError(f"HTTP {response.status_code}: non-JSON response", status_code=response.status_code)

            if not response.is_success:
                raise _classify_http_error(response.status_code, response.text)

            return body  # type: ignore[no-any-return]

        finally:
            self._rate_limiter.release()

    # ------------------------------------------------------------------
    # API-specific request helpers
    # ------------------------------------------------------------------

    async def _accounting_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", f"{ACCOUNTING_API_URL}/{path}", params=params)

    async def _accounting_post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", f"{ACCOUNTING_API_URL}/{path}", json_body=body)

    async def _accounting_put(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("PUT", f"{ACCOUNTING_API_URL}/{path}", json_body=body)

    async def _payroll_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", f"{PAYROLL_AU_API_URL}/{path}", params=params)

    async def _payroll_post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", f"{PAYROLL_AU_API_URL}/{path}", json_body=body)

    # ------------------------------------------------------------------
    # Identity / Connections
    # ------------------------------------------------------------------

    async def list_connections(self) -> list[dict[str, Any]]:
        """List connected Xero tenants/organisations."""
        result = await self._request("GET", IDENTITY_API_URL)
        if isinstance(result, list):
            return result
        return result.get("data", result.get("connections", [result]))

    # ------------------------------------------------------------------
    # Organisation
    # ------------------------------------------------------------------

    async def get_organisation(self) -> dict[str, Any]:
        """Get organisation details."""
        return await self._accounting_get("Organisation")

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    async def list_contacts(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        if include_archived:
            params["includeArchived"] = "true"
        return await self._accounting_get("Contacts", params)

    async def get_contact(self, contact_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"Contacts/{contact_id}")

    async def create_contact(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post("Contacts", body)

    async def update_contact(self, contact_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"Contacts/{contact_id}", body)

    async def archive_contact(self, contact_id: str) -> dict[str, Any]:
        return await self._accounting_post(
            f"Contacts/{contact_id}",
            {"ContactStatus": "ARCHIVED"},
        )

    # ------------------------------------------------------------------
    # Invoices (Sales — ACCREC)
    # ------------------------------------------------------------------

    async def list_invoices(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
        contact_ids: str | None = None,
        statuses: str | None = None,
        invoice_numbers: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        base_where = f'Type=="{INVOICE_TYPE_SALES}"'
        if where:
            params["where"] = f"{base_where} AND {where}"
        else:
            params["where"] = base_where
        if order:
            params["order"] = order
        if contact_ids:
            params["ContactIDs"] = contact_ids
        if statuses:
            params["Statuses"] = statuses
        if invoice_numbers:
            params["InvoiceNumbers"] = invoice_numbers
        return await self._accounting_get("Invoices", params)

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"Invoices/{invoice_id}")

    async def create_invoice(self, body: dict[str, Any]) -> dict[str, Any]:
        body.setdefault("Type", INVOICE_TYPE_SALES)
        return await self._accounting_put("Invoices", body)

    async def update_invoice(self, invoice_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"Invoices/{invoice_id}", body)

    async def void_invoice(self, invoice_id: str) -> dict[str, Any]:
        return await self._accounting_post(
            f"Invoices/{invoice_id}",
            {"Status": "VOIDED"},
        )

    async def email_invoice(self, invoice_id: str) -> dict[str, Any]:
        return await self._accounting_post(f"Invoices/{invoice_id}/Email")

    async def get_invoice_pdf(self, invoice_id: str) -> dict[str, Any]:
        """Get invoice as PDF — returns URL/binary info."""
        http = await self._get_http()
        headers = await self._headers()
        headers["Accept"] = "application/pdf"
        response = await http.get(
            f"{ACCOUNTING_API_URL}/Invoices/{invoice_id}",
            headers=headers,
        )
        if response.is_success:
            return {"content_type": "application/pdf", "size_bytes": len(response.content)}
        raise XeroError(f"PDF download failed: HTTP {response.status_code}", status_code=response.status_code)

    # ------------------------------------------------------------------
    # Bills (Purchase Invoices — ACCPAY)
    # ------------------------------------------------------------------

    async def list_bills(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
        statuses: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        base_where = f'Type=="{INVOICE_TYPE_BILL}"'
        if where:
            params["where"] = f"{base_where} AND {where}"
        else:
            params["where"] = base_where
        if order:
            params["order"] = order
        if statuses:
            params["Statuses"] = statuses
        return await self._accounting_get("Invoices", params)

    async def get_bill(self, bill_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"Invoices/{bill_id}")

    async def create_bill(self, body: dict[str, Any]) -> dict[str, Any]:
        body.setdefault("Type", INVOICE_TYPE_BILL)
        return await self._accounting_put("Invoices", body)

    async def update_bill(self, bill_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"Invoices/{bill_id}", body)

    async def void_bill(self, bill_id: str) -> dict[str, Any]:
        return await self._accounting_post(f"Invoices/{bill_id}", {"Status": "VOIDED"})

    # ------------------------------------------------------------------
    # Bank Transactions
    # ------------------------------------------------------------------

    async def list_bank_transactions(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("BankTransactions", params)

    async def get_bank_transaction(self, txn_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"BankTransactions/{txn_id}")

    async def create_bank_transaction(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_put("BankTransactions", body)

    async def update_bank_transaction(self, txn_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"BankTransactions/{txn_id}", body)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def list_payments(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("Payments", params)

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"Payments/{payment_id}")

    async def create_payment(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_put("Payments", body)

    async def delete_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._accounting_post(
            f"Payments/{payment_id}",
            {"Status": "DELETED"},
        )

    # ------------------------------------------------------------------
    # Credit Notes
    # ------------------------------------------------------------------

    async def list_credit_notes(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("CreditNotes", params)

    async def get_credit_note(self, credit_note_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"CreditNotes/{credit_note_id}")

    async def create_credit_note(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_put("CreditNotes", body)

    async def update_credit_note(self, credit_note_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"CreditNotes/{credit_note_id}", body)

    async def void_credit_note(self, credit_note_id: str) -> dict[str, Any]:
        return await self._accounting_post(
            f"CreditNotes/{credit_note_id}",
            {"Status": "VOIDED"},
        )

    # ------------------------------------------------------------------
    # Purchase Orders
    # ------------------------------------------------------------------

    async def list_purchase_orders(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("PurchaseOrders", params)

    async def get_purchase_order(self, po_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"PurchaseOrders/{po_id}")

    async def create_purchase_order(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_put("PurchaseOrders", body)

    async def update_purchase_order(self, po_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"PurchaseOrders/{po_id}", body)

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------

    async def list_quotes(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("Quotes", params)

    async def get_quote(self, quote_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"Quotes/{quote_id}")

    async def create_quote(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_put("Quotes", body)

    async def update_quote(self, quote_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_post(f"Quotes/{quote_id}", body)

    # ------------------------------------------------------------------
    # Manual Journals
    # ------------------------------------------------------------------

    async def list_manual_journals(
        self,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("ManualJournals", params)

    async def get_manual_journal(self, journal_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"ManualJournals/{journal_id}")

    async def create_manual_journal(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._accounting_put("ManualJournals", body)

    # ------------------------------------------------------------------
    # Accounts (Chart of Accounts)
    # ------------------------------------------------------------------

    async def list_accounts(self, where: str | None = None, order: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if where:
            params["where"] = where
        if order:
            params["order"] = order
        return await self._accounting_get("Accounts", params or None)

    async def get_account(self, account_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"Accounts/{account_id}")

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    async def get_profit_and_loss(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        periods: int | None = None,
        timeframe: str | None = None,
        tracking_category_id: str | None = None,
        tracking_option_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        if periods:
            params["periods"] = periods
        if timeframe:
            params["timeframe"] = timeframe
        if tracking_category_id:
            params["trackingCategoryID"] = tracking_category_id
        if tracking_option_id:
            params["trackingOptionID"] = tracking_option_id
        return await self._accounting_get("Reports/ProfitAndLoss", params or None)

    async def get_balance_sheet(
        self,
        date: str | None = None,
        periods: int | None = None,
        timeframe: str | None = None,
        tracking_category_id: str | None = None,
        tracking_option_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        if periods:
            params["periods"] = periods
        if timeframe:
            params["timeframe"] = timeframe
        if tracking_category_id:
            params["trackingCategoryID"] = tracking_category_id
        if tracking_option_id:
            params["trackingOptionID"] = tracking_option_id
        return await self._accounting_get("Reports/BalanceSheet", params or None)

    async def get_trial_balance(self, date: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        return await self._accounting_get("Reports/TrialBalance", params or None)

    async def get_aged_receivables(self, contact_id: str | None = None, date: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if contact_id:
            params["contactID"] = contact_id
        if date:
            params["date"] = date
        return await self._accounting_get("Reports/AgedReceivablesByContact", params or None)

    async def get_aged_payables(self, contact_id: str | None = None, date: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if contact_id:
            params["contactID"] = contact_id
        if date:
            params["date"] = date
        return await self._accounting_get("Reports/AgedPayablesByContact", params or None)

    # ------------------------------------------------------------------
    # Tax Rates
    # ------------------------------------------------------------------

    async def list_tax_rates(self, where: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if where:
            params["where"] = where
        return await self._accounting_get("TaxRates", params or None)

    # ------------------------------------------------------------------
    # Currencies
    # ------------------------------------------------------------------

    async def list_currencies(self) -> dict[str, Any]:
        return await self._accounting_get("Currencies")

    # ------------------------------------------------------------------
    # Tracking Categories
    # ------------------------------------------------------------------

    async def list_tracking_categories(self) -> dict[str, Any]:
        return await self._accounting_get("TrackingCategories")

    async def get_tracking_category(self, category_id: str) -> dict[str, Any]:
        return await self._accounting_get(f"TrackingCategories/{category_id}")

    # ------------------------------------------------------------------
    # Branding Themes
    # ------------------------------------------------------------------

    async def list_branding_themes(self) -> dict[str, Any]:
        return await self._accounting_get("BrandingThemes")

    # ------------------------------------------------------------------
    # Payroll AU — Employees
    # ------------------------------------------------------------------

    async def list_employees(self, where: str | None = None, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        return await self._payroll_get("Employees", params)

    async def get_employee(self, employee_id: str) -> dict[str, Any]:
        return await self._payroll_get(f"Employees/{employee_id}")

    async def create_employee(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._payroll_post("Employees", body)

    # ------------------------------------------------------------------
    # Payroll AU — Timesheets
    # ------------------------------------------------------------------

    async def list_timesheets(self, where: str | None = None, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if where:
            params["where"] = where
        return await self._payroll_get("Timesheets", params)

    async def get_timesheet(self, timesheet_id: str) -> dict[str, Any]:
        return await self._payroll_get(f"Timesheets/{timesheet_id}")

    async def create_timesheet(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._payroll_post("Timesheets", body)

    async def update_timesheet(self, timesheet_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._payroll_post(f"Timesheets/{timesheet_id}", body)

    async def approve_timesheet(self, timesheet_id: str) -> dict[str, Any]:
        return await self._payroll_post(f"Timesheets/{timesheet_id}/Approve")

    # ------------------------------------------------------------------
    # Payroll AU — Payslips
    # ------------------------------------------------------------------

    async def list_payslips(self, payrun_id: str) -> dict[str, Any]:
        return await self._payroll_get(f"PayRuns/{payrun_id}")

    async def get_payslip(self, payslip_id: str) -> dict[str, Any]:
        return await self._payroll_get(f"Payslip/{payslip_id}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client and auth client."""
        if self._http:
            await self._http.aclose()
        await self._auth.close()
