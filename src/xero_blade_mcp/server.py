"""Xero Blade MCP Server — Xero Accounting + Payroll AU API operations.

Token-efficient by default: pipe-delimited lists, field selection,
human-readable money, null-field omission. Write operations gated
behind XERO_WRITE_ENABLED=true. Destructive operations require
confirm=true.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from xero_blade_mcp.client import XeroClient
from xero_blade_mcp.formatters import (
    format_account_detail,
    format_account_list,
    format_bank_transaction_detail,
    format_bank_transaction_list,
    format_branding_theme_list,
    format_connection_list,
    format_contact_detail,
    format_contact_list,
    format_credit_note_list,
    format_currency_list,
    format_employee_detail,
    format_employee_list,
    format_invoice_detail,
    format_invoice_list,
    format_manual_journal_list,
    format_organisation_detail,
    format_payment_detail,
    format_payment_list,
    format_payslip_detail,
    format_payslip_list,
    format_purchase_order_list,
    format_quote_list,
    format_report,
    format_tax_rate_list,
    format_timesheet_detail,
    format_timesheet_list,
    format_tracking_category_list,
    format_webhook_verification,
)
from xero_blade_mcp.models import require_confirm, require_write, scrub_secrets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transport configuration
# ---------------------------------------------------------------------------

TRANSPORT = os.environ.get("XERO_MCP_TRANSPORT", "stdio")
HTTP_HOST = os.environ.get("XERO_MCP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("XERO_MCP_PORT", "8770"))

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "XeroBlade",
    instructions=(
        "Xero Accounting + Payroll AU API operations. Manage contacts, "
        "invoices, bills, bank transactions, payments, reports, and payroll. "
        "Token-efficient responses with pipe-delimited lists, field selection, "
        "and human-readable money. Write operations require XERO_WRITE_ENABLED=true. "
        "Destructive operations (void, delete, archive) require confirm=true."
    ),
)

_client: XeroClient | None = None


async def _get_client() -> XeroClient:
    """Get or create the XeroClient singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = XeroClient()
    return _client


def _error(e: Exception) -> str:
    """Format an error as a user-friendly string."""
    return f"Error: {scrub_secrets(str(e))}"


# ===========================================================================
# Meta / Connection tools
# ===========================================================================


@mcp.tool
async def xero_info() -> str:
    """Show Xero connection status, active tenant, and configuration."""
    try:
        client = await _get_client()
        connections = await client.list_connections()
        tenant_id = client._auth.get_tenant_id()
        write = "enabled" if os.environ.get("XERO_WRITE_ENABLED", "").lower() == "true" else "disabled"
        webhook = "configured" if os.environ.get("XERO_WEBHOOK_KEY", "").strip() else "not configured"

        tenant_name = "not set"
        if tenant_id:
            for c in connections:
                if c.get("tenantId") == tenant_id:
                    tenant_name = c.get("tenantName", tenant_id[:8])
                    break

        return (
            f"API: connected ({len(connections)} tenant(s))\n"
            f"Active Tenant: {tenant_name}\n"
            f"Writes: {write}\n"
            f"Webhook key: {webhook}"
        )
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_connections() -> str:
    """List connected Xero tenants/organisations. Use the tenantId to set XERO_TENANT_ID."""
    try:
        client = await _get_client()
        connections = await client.list_connections()
        return format_connection_list(connections)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_organisation() -> str:
    """Get organisation details — name, country, currency, tax settings, financial year."""
    try:
        client = await _get_client()
        result = await client.get_organisation()
        return format_organisation_detail(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Contact tools
# ===========================================================================


@mcp.tool
async def xero_contacts(
    search: Annotated[str | None, Field(description="Search contacts by name (contains match)")] = None,
    status: Annotated[str | None, Field(description="Filter: ACTIVE, ARCHIVED, GDPRREQUEST")] = None,
    page: Annotated[int, Field(description="Page number (100 per page)", ge=1)] = 1,
    include_archived: Annotated[bool, Field(description="Include archived contacts")] = False,
) -> str:
    """List contacts (customers and suppliers) with optional filters."""
    try:
        client = await _get_client()
        where = None
        if search:
            where = f'Name.Contains("{search}")'
        if status:
            status_filter = f'ContactStatus=="{status}"'
            where = f"{where} AND {status_filter}" if where else status_filter
        result = await client.list_contacts(where=where, page=page, include_archived=include_archived)
        return format_contact_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_contact(
    contact_id: Annotated[str, Field(description="Contact UUID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get contact detail — addresses, phone numbers, balances."""
    try:
        client = await _get_client()
        result = await client.get_contact(contact_id)
        return format_contact_detail(result, fields)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_contact(
    name: Annotated[str, Field(description="Contact name (required)")],
    email: Annotated[str | None, Field(description="Email address")] = None,
    first_name: Annotated[str | None, Field(description="First name")] = None,
    last_name: Annotated[str | None, Field(description="Last name")] = None,
    phone: Annotated[str | None, Field(description="Phone number")] = None,
    account_number: Annotated[str | None, Field(description="Account number")] = None,
    tax_number: Annotated[str | None, Field(description="Tax number (ABN for AU)")] = None,
) -> str:
    """Create a new contact. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        body: dict = {"Name": name}
        if email:
            body["EmailAddress"] = email
        if first_name:
            body["FirstName"] = first_name
        if last_name:
            body["LastName"] = last_name
        if phone:
            body["Phones"] = [{"PhoneType": "DEFAULT", "PhoneNumber": phone}]
        if account_number:
            body["AccountNumber"] = account_number
        if tax_number:
            body["TaxNumber"] = tax_number

        client = await _get_client()
        result = await client.create_contact(body)
        return format_contact_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_update_contact(
    contact_id: Annotated[str, Field(description="Contact UUID")],
    name: Annotated[str | None, Field(description="Updated name")] = None,
    email: Annotated[str | None, Field(description="Updated email")] = None,
    first_name: Annotated[str | None, Field(description="Updated first name")] = None,
    last_name: Annotated[str | None, Field(description="Updated last name")] = None,
    phone: Annotated[str | None, Field(description="Updated phone")] = None,
    account_number: Annotated[str | None, Field(description="Updated account number")] = None,
) -> str:
    """Update a contact. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        body: dict = {}
        if name:
            body["Name"] = name
        if email:
            body["EmailAddress"] = email
        if first_name:
            body["FirstName"] = first_name
        if last_name:
            body["LastName"] = last_name
        if phone:
            body["Phones"] = [{"PhoneType": "DEFAULT", "PhoneNumber": phone}]
        if account_number:
            body["AccountNumber"] = account_number
        if not body:
            return "Error: No fields to update."

        client = await _get_client()
        result = await client.update_contact(contact_id, body)
        return format_contact_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_archive_contact(
    contact_id: Annotated[str, Field(description="Contact UUID")],
    confirm: Annotated[bool, Field(description="Must be true to archive")] = False,
) -> str:
    """Archive a contact. Requires XERO_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return gate
    gate = require_confirm(confirm, "Archive contact")
    if gate:
        return gate
    try:
        client = await _get_client()
        result = await client.archive_contact(contact_id)
        return format_contact_detail(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Invoice tools (Sales — ACCREC)
# ===========================================================================


@mcp.tool
async def xero_invoices(
    status: Annotated[str | None, Field(description="Filter: DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED")] = None,
    contact_id: Annotated[str | None, Field(description="Filter by contact UUID")] = None,
    page: Annotated[int, Field(description="Page number (100 per page)", ge=1)] = 1,
    order: Annotated[str | None, Field(description="Sort: e.g., 'Date DESC', 'DueDate'")] = None,
) -> str:
    """List sales invoices with optional filters."""
    try:
        client = await _get_client()
        result = await client.list_invoices(
            statuses=status,
            contact_ids=contact_id,
            page=page,
            order=order,
        )
        return format_invoice_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_invoice(
    invoice_id: Annotated[str, Field(description="Invoice UUID or number")],
    fields: Annotated[str | None, Field(description="Comma-separated fields to return")] = None,
) -> str:
    """Get invoice detail — line items, payments, totals."""
    try:
        client = await _get_client()
        result = await client.get_invoice(invoice_id)
        return format_invoice_detail(result, fields)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_invoice(
    contact_id: Annotated[str, Field(description="Contact UUID")],
    line_items: Annotated[str, Field(description='JSON array: [{"Description":"...","Quantity":1,"UnitAmount":100}]')],
    date: Annotated[str | None, Field(description="Invoice date (YYYY-MM-DD)")] = None,
    due_date: Annotated[str | None, Field(description="Due date (YYYY-MM-DD)")] = None,
    reference: Annotated[str | None, Field(description="Reference/PO number")] = None,
    status: Annotated[str, Field(description="DRAFT or AUTHORISED")] = "DRAFT",
    currency: Annotated[str | None, Field(description="Currency code (default: org currency)")] = None,
) -> str:
    """Create a sales invoice. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        items = json.loads(line_items)
        body: dict = {
            "Type": "ACCREC",
            "Contact": {"ContactID": contact_id},
            "LineItems": items,
            "Status": status,
        }
        if date:
            body["Date"] = date
        if due_date:
            body["DueDate"] = due_date
        if reference:
            body["Reference"] = reference
        if currency:
            body["CurrencyCode"] = currency

        client = await _get_client()
        result = await client.create_invoice(body)
        return format_invoice_detail(result)
    except json.JSONDecodeError:
        return "Error: line_items must be valid JSON array."
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_update_invoice(
    invoice_id: Annotated[str, Field(description="Invoice UUID")],
    reference: Annotated[str | None, Field(description="Updated reference")] = None,
    due_date: Annotated[str | None, Field(description="Updated due date (YYYY-MM-DD)")] = None,
    status: Annotated[str | None, Field(description="New status: DRAFT, SUBMITTED, AUTHORISED")] = None,
) -> str:
    """Update a draft or submitted invoice. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        body: dict = {}
        if reference:
            body["Reference"] = reference
        if due_date:
            body["DueDate"] = due_date
        if status:
            body["Status"] = status
        if not body:
            return "Error: No fields to update."

        client = await _get_client()
        result = await client.update_invoice(invoice_id, body)
        return format_invoice_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_void_invoice(
    invoice_id: Annotated[str, Field(description="Invoice UUID")],
    confirm: Annotated[bool, Field(description="Must be true to void")] = False,
) -> str:
    """Void an invoice. Irreversible. Requires XERO_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return gate
    gate = require_confirm(confirm, "Void invoice")
    if gate:
        return gate
    try:
        client = await _get_client()
        result = await client.void_invoice(invoice_id)
        return format_invoice_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_email_invoice(
    invoice_id: Annotated[str, Field(description="Invoice UUID")],
) -> str:
    """Email an invoice to its contact. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        client = await _get_client()
        await client.email_invoice(invoice_id)
        return "Invoice emailed successfully."
    except Exception as e:
        return _error(e)


# ===========================================================================
# Bill tools (Purchase Invoices — ACCPAY)
# ===========================================================================


@mcp.tool
async def xero_bills(
    status: Annotated[str | None, Field(description="Filter: DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
    order: Annotated[str | None, Field(description="Sort: e.g., 'Date DESC'")] = None,
) -> str:
    """List purchase bills with optional filters."""
    try:
        client = await _get_client()
        result = await client.list_bills(statuses=status, page=page, order=order)
        return format_invoice_list(result, page, label="bills")
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_bill(
    bill_id: Annotated[str, Field(description="Bill UUID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields")] = None,
) -> str:
    """Get bill detail — line items, payments, totals."""
    try:
        client = await _get_client()
        result = await client.get_bill(bill_id)
        return format_invoice_detail(result, fields)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_bill(
    contact_id: Annotated[str, Field(description="Supplier contact UUID")],
    line_items: Annotated[str, Field(description="JSON array of line items")],
    date: Annotated[str | None, Field(description="Bill date (YYYY-MM-DD)")] = None,
    due_date: Annotated[str | None, Field(description="Due date (YYYY-MM-DD)")] = None,
    reference: Annotated[str | None, Field(description="Reference number")] = None,
    status: Annotated[str, Field(description="DRAFT or AUTHORISED")] = "DRAFT",
) -> str:
    """Create a purchase bill. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        items = json.loads(line_items)
        body: dict = {
            "Type": "ACCPAY",
            "Contact": {"ContactID": contact_id},
            "LineItems": items,
            "Status": status,
        }
        if date:
            body["Date"] = date
        if due_date:
            body["DueDate"] = due_date
        if reference:
            body["Reference"] = reference

        client = await _get_client()
        result = await client.create_bill(body)
        return format_invoice_detail(result)
    except json.JSONDecodeError:
        return "Error: line_items must be valid JSON array."
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_void_bill(
    bill_id: Annotated[str, Field(description="Bill UUID")],
    confirm: Annotated[bool, Field(description="Must be true to void")] = False,
) -> str:
    """Void a bill. Irreversible. Requires XERO_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return gate
    gate = require_confirm(confirm, "Void bill")
    if gate:
        return gate
    try:
        client = await _get_client()
        result = await client.void_bill(bill_id)
        return format_invoice_detail(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Bank Transaction tools
# ===========================================================================


@mcp.tool
async def xero_bank_transactions(
    bank_account: Annotated[str | None, Field(description="Filter by bank account name")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List bank transactions (spend/receive money)."""
    try:
        client = await _get_client()
        where = None
        if bank_account:
            where = f'BankAccount.Name=="{bank_account}"'
        result = await client.list_bank_transactions(where=where, page=page)
        return format_bank_transaction_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_bank_transaction(
    txn_id: Annotated[str, Field(description="Bank transaction UUID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields")] = None,
) -> str:
    """Get bank transaction detail — line items, account, contact."""
    try:
        client = await _get_client()
        result = await client.get_bank_transaction(txn_id)
        return format_bank_transaction_detail(result, fields)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_bank_transaction(
    txn_type: Annotated[str, Field(description="SPEND or RECEIVE")],
    contact_id: Annotated[str, Field(description="Contact UUID")],
    bank_account_id: Annotated[str, Field(description="Bank account UUID")],
    line_items: Annotated[str, Field(description="JSON array of line items")],
    date: Annotated[str | None, Field(description="Transaction date (YYYY-MM-DD)")] = None,
    reference: Annotated[str | None, Field(description="Reference")] = None,
) -> str:
    """Create a bank transaction (spend or receive money). Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        items = json.loads(line_items)
        body: dict = {
            "Type": txn_type,
            "Contact": {"ContactID": contact_id},
            "BankAccount": {"AccountID": bank_account_id},
            "LineItems": items,
        }
        if date:
            body["Date"] = date
        if reference:
            body["Reference"] = reference

        client = await _get_client()
        result = await client.create_bank_transaction(body)
        return format_bank_transaction_detail(result)
    except json.JSONDecodeError:
        return "Error: line_items must be valid JSON array."
    except Exception as e:
        return _error(e)


# ===========================================================================
# Payment tools
# ===========================================================================


@mcp.tool
async def xero_payments(
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List payments."""
    try:
        client = await _get_client()
        result = await client.list_payments(page=page)
        return format_payment_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_payment(
    payment_id: Annotated[str, Field(description="Payment UUID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields")] = None,
) -> str:
    """Get payment detail — amount, date, invoice, account."""
    try:
        client = await _get_client()
        result = await client.get_payment(payment_id)
        return format_payment_detail(result, fields)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_payment(
    invoice_id: Annotated[str, Field(description="Invoice UUID to pay against")],
    account_id: Annotated[str, Field(description="Bank account UUID")],
    amount: Annotated[float, Field(description="Payment amount")],
    date: Annotated[str | None, Field(description="Payment date (YYYY-MM-DD)")] = None,
    reference: Annotated[str | None, Field(description="Payment reference")] = None,
) -> str:
    """Record a payment against an invoice or bill. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        body: dict = {
            "Invoice": {"InvoiceID": invoice_id},
            "Account": {"AccountID": account_id},
            "Amount": amount,
        }
        if date:
            body["Date"] = date
        if reference:
            body["Reference"] = reference

        client = await _get_client()
        result = await client.create_payment(body)
        return format_payment_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_delete_payment(
    payment_id: Annotated[str, Field(description="Payment UUID")],
    confirm: Annotated[bool, Field(description="Must be true to delete")] = False,
) -> str:
    """Delete a payment. Requires XERO_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return gate
    gate = require_confirm(confirm, "Delete payment")
    if gate:
        return gate
    try:
        client = await _get_client()
        result = await client.delete_payment(payment_id)
        return "Payment deleted." if not result else format_payment_detail(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Credit Note tools
# ===========================================================================


@mcp.tool
async def xero_credit_notes(
    status: Annotated[str | None, Field(description="Filter: DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List credit notes."""
    try:
        where = f'Status=="{status}"' if status else None
        client = await _get_client()
        result = await client.list_credit_notes(where=where, page=page)
        return format_credit_note_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_credit_note(
    contact_id: Annotated[str, Field(description="Contact UUID")],
    line_items: Annotated[str, Field(description="JSON array of line items")],
    credit_note_type: Annotated[str, Field(description="ACCRECCREDIT or ACCPAYCREDIT")] = "ACCRECCREDIT",
    date: Annotated[str | None, Field(description="Credit note date (YYYY-MM-DD)")] = None,
    reference: Annotated[str | None, Field(description="Reference")] = None,
) -> str:
    """Create a credit note. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        items = json.loads(line_items)
        body: dict = {
            "Type": credit_note_type,
            "Contact": {"ContactID": contact_id},
            "LineItems": items,
        }
        if date:
            body["Date"] = date
        if reference:
            body["Reference"] = reference

        client = await _get_client()
        result = await client.create_credit_note(body)
        return f"Credit note created: {result.get('CreditNotes', [{}])[0].get('CreditNoteID', '?')}"
    except json.JSONDecodeError:
        return "Error: line_items must be valid JSON array."
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_void_credit_note(
    credit_note_id: Annotated[str, Field(description="Credit note UUID")],
    confirm: Annotated[bool, Field(description="Must be true to void")] = False,
) -> str:
    """Void a credit note. Irreversible. Requires XERO_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return gate
    gate = require_confirm(confirm, "Void credit note")
    if gate:
        return gate
    try:
        client = await _get_client()
        await client.void_credit_note(credit_note_id)
        return "Credit note voided."
    except Exception as e:
        return _error(e)


# ===========================================================================
# Purchase Order tools
# ===========================================================================


@mcp.tool
async def xero_purchase_orders(
    status: Annotated[str | None, Field(description="Filter: DRAFT, SUBMITTED, AUTHORISED, BILLED, DELETED")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List purchase orders."""
    try:
        where = f'Status=="{status}"' if status else None
        client = await _get_client()
        result = await client.list_purchase_orders(where=where, page=page)
        return format_purchase_order_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_purchase_order(
    contact_id: Annotated[str, Field(description="Supplier contact UUID")],
    line_items: Annotated[str, Field(description="JSON array of line items")],
    date: Annotated[str | None, Field(description="PO date (YYYY-MM-DD)")] = None,
    delivery_date: Annotated[str | None, Field(description="Expected delivery date")] = None,
    reference: Annotated[str | None, Field(description="Reference")] = None,
) -> str:
    """Create a purchase order. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        items = json.loads(line_items)
        body: dict = {
            "Contact": {"ContactID": contact_id},
            "LineItems": items,
        }
        if date:
            body["Date"] = date
        if delivery_date:
            body["DeliveryDate"] = delivery_date
        if reference:
            body["Reference"] = reference

        client = await _get_client()
        result = await client.create_purchase_order(body)
        return f"PO created: {result.get('PurchaseOrders', [{}])[0].get('PurchaseOrderNumber', '?')}"
    except json.JSONDecodeError:
        return "Error: line_items must be valid JSON array."
    except Exception as e:
        return _error(e)


# ===========================================================================
# Quote tools
# ===========================================================================


@mcp.tool
async def xero_quotes(
    status: Annotated[str | None, Field(description="Filter: DRAFT, SENT, ACCEPTED, DECLINED, INVOICED")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List quotes."""
    try:
        where = f'Status=="{status}"' if status else None
        client = await _get_client()
        result = await client.list_quotes(where=where, page=page)
        return format_quote_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_quote(
    contact_id: Annotated[str, Field(description="Contact UUID")],
    line_items: Annotated[str, Field(description="JSON array of line items")],
    date: Annotated[str | None, Field(description="Quote date (YYYY-MM-DD)")] = None,
    expiry_date: Annotated[str | None, Field(description="Expiry date (YYYY-MM-DD)")] = None,
    reference: Annotated[str | None, Field(description="Reference")] = None,
    title: Annotated[str | None, Field(description="Quote title")] = None,
    summary: Annotated[str | None, Field(description="Quote summary")] = None,
) -> str:
    """Create a quote. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        items = json.loads(line_items)
        body: dict = {
            "Contact": {"ContactID": contact_id},
            "LineItems": items,
        }
        if date:
            body["Date"] = date
        if expiry_date:
            body["ExpiryDate"] = expiry_date
        if reference:
            body["Reference"] = reference
        if title:
            body["Title"] = title
        if summary:
            body["Summary"] = summary

        client = await _get_client()
        result = await client.create_quote(body)
        return f"Quote created: {result.get('Quotes', [{}])[0].get('QuoteNumber', '?')}"
    except json.JSONDecodeError:
        return "Error: line_items must be valid JSON array."
    except Exception as e:
        return _error(e)


# ===========================================================================
# Account tools (Chart of Accounts)
# ===========================================================================


@mcp.tool
async def xero_accounts(
    account_type: Annotated[str | None, Field(description="Filter: BANK, REVENUE, EXPENSE, etc.")] = None,
    account_class: Annotated[
        str | None, Field(description="Filter: ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE")
    ] = None,  # noqa: E501
) -> str:
    """List chart of accounts."""
    try:
        where_parts = []
        if account_type:
            where_parts.append(f'Type=="{account_type}"')
        if account_class:
            where_parts.append(f'Class=="{account_class}"')
        where = " AND ".join(where_parts) if where_parts else None

        client = await _get_client()
        result = await client.list_accounts(where=where)
        return format_account_list(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_account(
    account_id: Annotated[str, Field(description="Account UUID")],
    fields: Annotated[str | None, Field(description="Comma-separated fields")] = None,
) -> str:
    """Get account detail — type, class, tax type, bank info."""
    try:
        client = await _get_client()
        result = await client.get_account(account_id)
        return format_account_detail(result, fields)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Manual Journal tools
# ===========================================================================


@mcp.tool
async def xero_manual_journals(
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List manual journal entries."""
    try:
        client = await _get_client()
        result = await client.list_manual_journals(page=page)
        return format_manual_journal_list(result, page)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Report tools
# ===========================================================================


@mcp.tool
async def xero_profit_loss(
    from_date: Annotated[str | None, Field(description="Start date (YYYY-MM-DD)")] = None,
    to_date: Annotated[str | None, Field(description="End date (YYYY-MM-DD)")] = None,
    periods: Annotated[int | None, Field(description="Number of comparison periods")] = None,
    timeframe: Annotated[str | None, Field(description="MONTH, QUARTER, or YEAR")] = None,
) -> str:
    """Get Profit & Loss report for a date range."""
    try:
        client = await _get_client()
        result = await client.get_profit_and_loss(
            from_date=from_date, to_date=to_date, periods=periods, timeframe=timeframe
        )
        return format_report(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_balance_sheet(
    date: Annotated[str | None, Field(description="Report date (YYYY-MM-DD)")] = None,
    periods: Annotated[int | None, Field(description="Number of comparison periods")] = None,
    timeframe: Annotated[str | None, Field(description="MONTH, QUARTER, or YEAR")] = None,
) -> str:
    """Get Balance Sheet report as at a given date."""
    try:
        client = await _get_client()
        result = await client.get_balance_sheet(date=date, periods=periods, timeframe=timeframe)
        return format_report(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_trial_balance(
    date: Annotated[str | None, Field(description="Report date (YYYY-MM-DD)")] = None,
) -> str:
    """Get Trial Balance report as at a given date."""
    try:
        client = await _get_client()
        result = await client.get_trial_balance(date=date)
        return format_report(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_aged_receivables(
    contact_id: Annotated[str | None, Field(description="Filter by contact UUID")] = None,
    date: Annotated[str | None, Field(description="Report date (YYYY-MM-DD)")] = None,
) -> str:
    """Get Aged Receivables report with period breakdown."""
    try:
        client = await _get_client()
        result = await client.get_aged_receivables(contact_id=contact_id, date=date)
        return format_report(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_aged_payables(
    contact_id: Annotated[str | None, Field(description="Filter by contact UUID")] = None,
    date: Annotated[str | None, Field(description="Report date (YYYY-MM-DD)")] = None,
) -> str:
    """Get Aged Payables report with period breakdown."""
    try:
        client = await _get_client()
        result = await client.get_aged_payables(contact_id=contact_id, date=date)
        return format_report(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Reference data tools
# ===========================================================================


@mcp.tool
async def xero_tax_rates() -> str:
    """List tax rates and their effective percentages."""
    try:
        client = await _get_client()
        result = await client.list_tax_rates()
        return format_tax_rate_list(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_currencies() -> str:
    """List active currencies configured for the organisation."""
    try:
        client = await _get_client()
        result = await client.list_currencies()
        return format_currency_list(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_tracking_categories() -> str:
    """List tracking categories and their options for cost allocation."""
    try:
        client = await _get_client()
        result = await client.list_tracking_categories()
        return format_tracking_category_list(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_branding_themes() -> str:
    """List branding themes for invoice/quote customisation."""
    try:
        client = await _get_client()
        result = await client.list_branding_themes()
        return format_branding_theme_list(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Payroll AU tools
# ===========================================================================


@mcp.tool
async def xero_employees(
    status: Annotated[str | None, Field(description="Filter: ACTIVE, TERMINATED")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List payroll employees (AU Payroll API)."""
    try:
        where = f'Status=="{status}"' if status else None
        client = await _get_client()
        result = await client.list_employees(where=where, page=page)
        return format_employee_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_employee(
    employee_id: Annotated[str, Field(description="Employee UUID")],
) -> str:
    """Get employee detail — tax declaration, super, leave, address."""
    try:
        client = await _get_client()
        result = await client.get_employee(employee_id)
        return format_employee_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_timesheets(
    status: Annotated[str | None, Field(description="Filter: DRAFT, PROCESSED, APPROVED")] = None,
    page: Annotated[int, Field(description="Page number", ge=1)] = 1,
) -> str:
    """List payroll timesheets (AU Payroll API)."""
    try:
        where = f'Status=="{status}"' if status else None
        client = await _get_client()
        result = await client.list_timesheets(where=where, page=page)
        return format_timesheet_list(result, page)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_timesheet(
    timesheet_id: Annotated[str, Field(description="Timesheet UUID")],
) -> str:
    """Get timesheet detail — lines, hours, earnings rates."""
    try:
        client = await _get_client()
        result = await client.get_timesheet(timesheet_id)
        return format_timesheet_detail(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_create_timesheet(
    employee_id: Annotated[str, Field(description="Employee UUID")],
    start_date: Annotated[str, Field(description="Period start date (YYYY-MM-DD)")],
    end_date: Annotated[str, Field(description="Period end date (YYYY-MM-DD)")],
    timesheet_lines: Annotated[str, Field(description='JSON: [{"EarningsRateID":"...","NumberOfUnits":[8,8,...]}]')],
) -> str:
    """Create a timesheet. Requires XERO_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        lines_data = json.loads(timesheet_lines)
        body: dict = {
            "EmployeeID": employee_id,
            "StartDate": start_date,
            "EndDate": end_date,
            "TimesheetLines": lines_data,
        }
        client = await _get_client()
        result = await client.create_timesheet(body)
        return format_timesheet_detail(result)
    except json.JSONDecodeError:
        return "Error: timesheet_lines must be valid JSON array."
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_approve_timesheet(
    timesheet_id: Annotated[str, Field(description="Timesheet UUID")],
    confirm: Annotated[bool, Field(description="Must be true to approve")] = False,
) -> str:
    """Approve a timesheet. Requires XERO_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return gate
    gate = require_confirm(confirm, "Approve timesheet")
    if gate:
        return gate
    try:
        client = await _get_client()
        await client.approve_timesheet(timesheet_id)
        return "Timesheet approved."
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_payslips(
    payrun_id: Annotated[str, Field(description="Pay run UUID")],
) -> str:
    """List payslips for a pay run (AU Payroll API)."""
    try:
        client = await _get_client()
        result = await client.list_payslips(payrun_id)
        return format_payslip_list(result)
    except Exception as e:
        return _error(e)


@mcp.tool
async def xero_payslip(
    payslip_id: Annotated[str, Field(description="Payslip UUID")],
) -> str:
    """Get payslip detail — earnings, deductions, super, tax."""
    try:
        client = await _get_client()
        result = await client.get_payslip(payslip_id)
        return format_payslip_detail(result)
    except Exception as e:
        return _error(e)


# ===========================================================================
# Webhook verification tool
# ===========================================================================


@mcp.tool
async def xero_verify_webhook(
    raw_body: Annotated[str, Field(description="Raw webhook request body (JSON string)")],
    signature_header: Annotated[str, Field(description="X-Xero-Signature header value (base64)")],
) -> str:
    """Verify a Xero webhook HMAC-SHA256 signature.

    Xero signs webhook payloads with HMAC-SHA256 using your webhook key.
    The signature is base64-encoded in the X-Xero-Signature header.
    """
    webhook_key = os.environ.get("XERO_WEBHOOK_KEY", "").strip()
    if not webhook_key:
        return "Error: XERO_WEBHOOK_KEY not configured."

    try:
        import base64

        expected = hmac.new(
            webhook_key.encode("utf-8"),
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_b64 = base64.b64encode(expected).decode("utf-8")

        if hmac.compare_digest(expected_b64, signature_header):
            payload = json.loads(raw_body)
            events = payload.get("events", [])
            return format_webhook_verification({"valid": True, "event_count": len(events)})

        return format_webhook_verification({"valid": False, "error": "Signature mismatch"})
    except (ValueError, json.JSONDecodeError) as e:
        return format_webhook_verification({"valid": False, "error": str(e)})


# ===========================================================================
# Server entrypoint
# ===========================================================================


def main() -> None:
    """Start the Xero Blade MCP server."""
    if TRANSPORT == "http":
        mcp.run(
            transport="streamable-http",
            host=HTTP_HOST,
            port=HTTP_PORT,
        )
    else:
        mcp.run(transport="stdio")
