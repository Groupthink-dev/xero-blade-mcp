"""Tests for xero_blade_mcp.server — tool functions, gates, webhook verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import xero_blade_mcp.server as server_mod
from xero_blade_mcp.server import (
    _error,
    xero_account,
    xero_accounts,
    xero_aged_payables,
    xero_aged_receivables,
    xero_approve_timesheet,
    xero_archive_contact,
    xero_balance_sheet,
    xero_bank_transaction,
    xero_bank_transactions,
    xero_bill,
    xero_bills,
    xero_branding_themes,
    xero_connections,
    xero_contact,
    xero_contacts,
    xero_create_bank_transaction,
    xero_create_bill,
    xero_create_contact,
    xero_create_credit_note,
    xero_create_invoice,
    xero_create_payment,
    xero_create_purchase_order,
    xero_create_quote,
    xero_create_timesheet,
    xero_credit_notes,
    xero_currencies,
    xero_delete_payment,
    xero_email_invoice,
    xero_employee,
    xero_employees,
    xero_info,
    xero_invoice,
    xero_invoices,
    xero_manual_journals,
    xero_organisation,
    xero_payment,
    xero_payments,
    xero_payslip,
    xero_payslips,
    xero_profit_loss,
    xero_purchase_orders,
    xero_quotes,
    xero_tax_rates,
    xero_timesheet,
    xero_timesheets,
    xero_tracking_categories,
    xero_trial_balance,
    xero_update_contact,
    xero_update_invoice,
    xero_verify_webhook,
    xero_void_bill,
    xero_void_credit_note,
    xero_void_invoice,
)

from .conftest import (
    SAMPLE_ACCOUNT,
    SAMPLE_BANK_TRANSACTION,
    SAMPLE_CONNECTION,
    SAMPLE_CONTACT,
    SAMPLE_CREDIT_NOTE,
    SAMPLE_EMPLOYEE,
    SAMPLE_INVOICE,
    SAMPLE_ORGANISATION,
    SAMPLE_PAYMENT,
    SAMPLE_PAYSLIP,
    SAMPLE_PURCHASE_ORDER,
    SAMPLE_QUOTE,
    SAMPLE_REPORT,
    SAMPLE_TIMESHEET,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    """Reset the global client singleton between tests."""
    server_mod._client = None


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock XeroClient and inject it as the singleton."""
    client = AsyncMock()
    # _auth.get_tenant_id is a sync method, so use MagicMock for _auth
    client._auth = MagicMock()
    client._auth.get_tenant_id.return_value = "test-tenant"
    server_mod._client = client
    return client


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


class TestErrorHelper:
    def test_formats_exception(self) -> None:
        result = _error(ValueError("something went wrong"))
        assert result.startswith("Error:")
        assert "something went wrong" in result

    def test_scrubs_secrets(self) -> None:
        result = _error(Exception("Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"))
        assert "eyJ" not in result


# ===========================================================================
# Meta / Connection tools
# ===========================================================================


class TestXeroInfo:
    async def test_info_success(self, mock_client: AsyncMock) -> None:
        mock_client.list_connections.return_value = [SAMPLE_CONNECTION]
        mock_client._auth.get_tenant_id.return_value = SAMPLE_CONNECTION["tenantId"]
        result = await xero_info()
        assert "connected" in result
        assert "1 tenant" in result
        assert "Test Company" in result

    async def test_info_no_tenant(self, mock_client: AsyncMock) -> None:
        mock_client.list_connections.return_value = []
        mock_client._auth.get_tenant_id.return_value = None
        result = await xero_info()
        assert "not set" in result

    async def test_info_writes_disabled(self, mock_client: AsyncMock) -> None:
        mock_client.list_connections.return_value = []
        mock_client._auth.get_tenant_id.return_value = None
        result = await xero_info()
        assert "disabled" in result

    async def test_info_writes_enabled(self, mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "true")
        mock_client.list_connections.return_value = []
        mock_client._auth.get_tenant_id.return_value = None
        result = await xero_info()
        assert "enabled" in result

    async def test_info_error(self, mock_client: AsyncMock) -> None:
        mock_client.list_connections.side_effect = Exception("API down")
        result = await xero_info()
        assert "Error:" in result


class TestXeroConnections:
    async def test_connections(self, mock_client: AsyncMock) -> None:
        mock_client.list_connections.return_value = [SAMPLE_CONNECTION]
        result = await xero_connections()
        assert "Test Company" in result

    async def test_connections_error(self, mock_client: AsyncMock) -> None:
        mock_client.list_connections.side_effect = Exception("fail")
        result = await xero_connections()
        assert "Error:" in result


class TestXeroOrganisation:
    async def test_organisation(self, mock_client: AsyncMock) -> None:
        mock_client.get_organisation.return_value = SAMPLE_ORGANISATION
        result = await xero_organisation()
        assert "Test Company" in result


# ===========================================================================
# Contact tools — READ
# ===========================================================================


class TestContactReadTools:
    async def test_contacts_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_contacts.return_value = {"Contacts": [SAMPLE_CONTACT]}
        result = await xero_contacts()
        assert "Acme Corporation" in result

    async def test_contacts_with_search(self, mock_client: AsyncMock) -> None:
        mock_client.list_contacts.return_value = {"Contacts": [SAMPLE_CONTACT]}
        await xero_contacts(search="Acme")
        call_kwargs = mock_client.list_contacts.call_args[1]
        assert 'Name.Contains("Acme")' in call_kwargs["where"]

    async def test_contacts_with_status_filter(self, mock_client: AsyncMock) -> None:
        mock_client.list_contacts.return_value = {"Contacts": []}
        await xero_contacts(status="ARCHIVED")
        call_kwargs = mock_client.list_contacts.call_args[1]
        assert 'ContactStatus=="ARCHIVED"' in call_kwargs["where"]

    async def test_contacts_combined_filters(self, mock_client: AsyncMock) -> None:
        mock_client.list_contacts.return_value = {"Contacts": []}
        await xero_contacts(search="Acme", status="ACTIVE")
        call_kwargs = mock_client.list_contacts.call_args[1]
        assert "Name.Contains" in call_kwargs["where"]
        assert "ContactStatus" in call_kwargs["where"]

    async def test_contact_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_contact.return_value = {"Contacts": [SAMPLE_CONTACT]}
        result = await xero_contact("c-123")
        assert "Acme Corporation" in result

    async def test_contact_detail_with_fields(self, mock_client: AsyncMock) -> None:
        mock_client.get_contact.return_value = {"Contacts": [SAMPLE_CONTACT]}
        result = await xero_contact("c-123", fields="Name,ContactStatus")
        assert "Acme Corporation" in result

    async def test_contact_error(self, mock_client: AsyncMock) -> None:
        mock_client.list_contacts.side_effect = Exception("network fail")
        result = await xero_contacts()
        assert "Error:" in result


# ===========================================================================
# Contact tools — WRITE
# ===========================================================================


class TestContactWriteTools:
    async def test_create_contact_blocked_without_write(self, mock_client: AsyncMock) -> None:
        result = await xero_create_contact(name="Test")
        assert "Write operations are disabled" in result
        mock_client.create_contact.assert_not_called()

    async def test_create_contact_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_contact.return_value = {"Contacts": [SAMPLE_CONTACT]}
        result = await xero_create_contact(name="Acme", email="a@b.com")
        assert "Acme" in result
        body = mock_client.create_contact.call_args[0][0]
        assert body["Name"] == "Acme"
        assert body["EmailAddress"] == "a@b.com"

    async def test_create_contact_all_fields(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_contact.return_value = {"Contacts": [SAMPLE_CONTACT]}
        await xero_create_contact(
            name="Test",
            email="t@t.com",
            first_name="John",
            last_name="Doe",
            phone="5551234",
            account_number="A-001",
            tax_number="123",
        )
        body = mock_client.create_contact.call_args[0][0]
        assert body["FirstName"] == "John"
        assert body["LastName"] == "Doe"
        assert body["Phones"][0]["PhoneNumber"] == "5551234"
        assert body["AccountNumber"] == "A-001"
        assert body["TaxNumber"] == "123"

    async def test_update_contact_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_update_contact(contact_id="c-1", name="New Name")
        assert "Write operations are disabled" in result

    async def test_update_contact_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.update_contact.return_value = {"Contacts": [SAMPLE_CONTACT]}
        result = await xero_update_contact(contact_id="c-1", name="New Name")
        assert "Acme" in result  # from mock return

    async def test_update_contact_no_fields(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_update_contact(contact_id="c-1")
        assert "No fields to update" in result

    async def test_archive_contact_blocked_without_write(self, mock_client: AsyncMock) -> None:
        result = await xero_archive_contact(contact_id="c-1", confirm=True)
        assert "Write operations are disabled" in result

    async def test_archive_contact_blocked_without_confirm(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_archive_contact(contact_id="c-1", confirm=False)
        assert "confirm=true" in result

    async def test_archive_contact_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.archive_contact.return_value = {"Contacts": [SAMPLE_CONTACT]}
        result = await xero_archive_contact(contact_id="c-1", confirm=True)
        assert "Acme" in result


# ===========================================================================
# Invoice tools — READ
# ===========================================================================


class TestInvoiceReadTools:
    async def test_invoices_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_invoices.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_invoices()
        assert "INV-0001" in result

    async def test_invoices_with_status(self, mock_client: AsyncMock) -> None:
        mock_client.list_invoices.return_value = {"Invoices": []}
        await xero_invoices(status="AUTHORISED")
        call_kwargs = mock_client.list_invoices.call_args[1]
        assert call_kwargs["statuses"] == "AUTHORISED"

    async def test_invoice_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_invoice.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_invoice("inv-1")
        assert "INV-0001" in result


# ===========================================================================
# Invoice tools — WRITE
# ===========================================================================


class TestInvoiceWriteTools:
    async def test_create_invoice_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_invoice(
            contact_id="c-1",
            line_items='[{"Description":"Test","Quantity":1,"UnitAmount":100}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_invoice_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_invoice.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_create_invoice(
            contact_id="c-1",
            line_items='[{"Description":"Test","Quantity":1,"UnitAmount":100,"AccountCode":"200"}]',
            date="2026-03-15",
            due_date="2026-04-15",
            reference="PO-999",
            currency="USD",
        )
        assert "INV-0001" in result

    async def test_create_invoice_invalid_json(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_create_invoice(contact_id="c-1", line_items="not json")
        assert "must be valid JSON" in result

    async def test_update_invoice_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_update_invoice(invoice_id="inv-1", reference="new-ref")
        assert "Write operations are disabled" in result

    async def test_update_invoice_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.update_invoice.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_update_invoice(invoice_id="inv-1", reference="new-ref")
        assert "INV-0001" in result

    async def test_update_invoice_no_fields(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_update_invoice(invoice_id="inv-1")
        assert "No fields to update" in result

    async def test_void_invoice_blocked_write(self, mock_client: AsyncMock) -> None:
        result = await xero_void_invoice(invoice_id="inv-1", confirm=True)
        assert "Write operations are disabled" in result

    async def test_void_invoice_blocked_confirm(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_void_invoice(invoice_id="inv-1", confirm=False)
        assert "confirm=true" in result

    async def test_void_invoice_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.void_invoice.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_void_invoice(invoice_id="inv-1", confirm=True)
        assert "INV-0001" in result

    async def test_email_invoice_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_email_invoice(invoice_id="inv-1")
        assert "Write operations are disabled" in result

    async def test_email_invoice_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.email_invoice.return_value = {}
        result = await xero_email_invoice(invoice_id="inv-1")
        assert "emailed successfully" in result


# ===========================================================================
# Bill tools
# ===========================================================================


class TestBillTools:
    async def test_bills_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_bills.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_bills()
        assert "INV-0001" in result

    async def test_bill_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_bill.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_bill("bill-1")
        assert "INV-0001" in result

    async def test_create_bill_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_bill(
            contact_id="c-1",
            line_items='[{"Description":"Supply","Quantity":1,"UnitAmount":50}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_bill_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_bill.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_create_bill(
            contact_id="c-1",
            line_items='[{"Description":"Supply","Quantity":1,"UnitAmount":50}]',
        )
        assert "INV-0001" in result

    async def test_create_bill_invalid_json(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_create_bill(contact_id="c-1", line_items="bad")
        assert "must be valid JSON" in result

    async def test_void_bill_blocked_write(self, mock_client: AsyncMock) -> None:
        result = await xero_void_bill(bill_id="b-1", confirm=True)
        assert "Write operations are disabled" in result

    async def test_void_bill_blocked_confirm(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_void_bill(bill_id="b-1", confirm=False)
        assert "confirm=true" in result

    async def test_void_bill_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.void_bill.return_value = {"Invoices": [SAMPLE_INVOICE]}
        result = await xero_void_bill(bill_id="b-1", confirm=True)
        assert "INV-0001" in result


# ===========================================================================
# Bank Transaction tools
# ===========================================================================


class TestBankTransactionTools:
    async def test_bank_transactions_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_bank_transactions.return_value = {"BankTransactions": [SAMPLE_BANK_TRANSACTION]}
        result = await xero_bank_transactions()
        assert "SPEND" in result

    async def test_bank_transactions_with_filter(self, mock_client: AsyncMock) -> None:
        mock_client.list_bank_transactions.return_value = {"BankTransactions": []}
        await xero_bank_transactions(bank_account="Business Cheque")
        call_kwargs = mock_client.list_bank_transactions.call_args[1]
        assert 'BankAccount.Name=="Business Cheque"' in call_kwargs["where"]

    async def test_bank_transaction_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_bank_transaction.return_value = {"BankTransactions": [SAMPLE_BANK_TRANSACTION]}
        result = await xero_bank_transaction("bt-1")
        assert "SPEND" in result

    async def test_create_bank_transaction_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_bank_transaction(
            txn_type="SPEND",
            contact_id="c-1",
            bank_account_id="ba-1",
            line_items='[{"Description":"Test","UnitAmount":10,"AccountCode":"200"}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_bank_transaction_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_bank_transaction.return_value = {"BankTransactions": [SAMPLE_BANK_TRANSACTION]}
        result = await xero_create_bank_transaction(
            txn_type="SPEND",
            contact_id="c-1",
            bank_account_id="ba-1",
            line_items='[{"Description":"Test","UnitAmount":10,"AccountCode":"200"}]',
        )
        assert "SPEND" in result

    async def test_create_bank_transaction_invalid_json(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_create_bank_transaction(
            txn_type="SPEND",
            contact_id="c-1",
            bank_account_id="ba-1",
            line_items="not json",
        )
        assert "must be valid JSON" in result


# ===========================================================================
# Payment tools
# ===========================================================================


class TestPaymentTools:
    async def test_payments_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_payments.return_value = {"Payments": [SAMPLE_PAYMENT]}
        result = await xero_payments()
        assert "A$500.00 AUD" in result

    async def test_payment_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_payment.return_value = {"Payments": [SAMPLE_PAYMENT]}
        result = await xero_payment("pay-1")
        assert "A$500.00 AUD" in result

    async def test_create_payment_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_payment(invoice_id="inv-1", account_id="acc-1", amount=100.0)
        assert "Write operations are disabled" in result

    async def test_create_payment_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_payment.return_value = {"Payments": [SAMPLE_PAYMENT]}
        result = await xero_create_payment(
            invoice_id="inv-1",
            account_id="acc-1",
            amount=500.00,
            date="2026-03-20",
            reference="PAY-001",
        )
        assert "A$500.00 AUD" in result

    async def test_delete_payment_blocked_write(self, mock_client: AsyncMock) -> None:
        result = await xero_delete_payment(payment_id="pay-1", confirm=True)
        assert "Write operations are disabled" in result

    async def test_delete_payment_blocked_confirm(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_delete_payment(payment_id="pay-1", confirm=False)
        assert "confirm=true" in result

    async def test_delete_payment_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.delete_payment.return_value = {"Payments": [SAMPLE_PAYMENT]}
        result = await xero_delete_payment(payment_id="pay-1", confirm=True)
        assert "A$500.00 AUD" in result

    async def test_delete_payment_empty_result(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.delete_payment.return_value = {}
        result = await xero_delete_payment(payment_id="pay-1", confirm=True)
        assert "Payment deleted" in result


# ===========================================================================
# Credit Note tools
# ===========================================================================


class TestCreditNoteTools:
    async def test_credit_notes_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_credit_notes.return_value = {"CreditNotes": [SAMPLE_CREDIT_NOTE]}
        result = await xero_credit_notes()
        assert "CN-0001" in result

    async def test_credit_notes_with_status(self, mock_client: AsyncMock) -> None:
        mock_client.list_credit_notes.return_value = {"CreditNotes": []}
        await xero_credit_notes(status="AUTHORISED")
        call_kwargs = mock_client.list_credit_notes.call_args[1]
        assert 'Status=="AUTHORISED"' in call_kwargs["where"]

    async def test_create_credit_note_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_credit_note(
            contact_id="c-1",
            line_items='[{"Description":"Refund","UnitAmount":50,"AccountCode":"200"}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_credit_note_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_credit_note.return_value = {"CreditNotes": [{"CreditNoteID": "cn-abc"}]}
        result = await xero_create_credit_note(
            contact_id="c-1",
            line_items='[{"Description":"Refund","UnitAmount":50,"AccountCode":"200"}]',
        )
        assert "cn-abc" in result

    async def test_create_credit_note_invalid_json(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_create_credit_note(contact_id="c-1", line_items="bad")
        assert "must be valid JSON" in result

    async def test_void_credit_note_blocked_write(self, mock_client: AsyncMock) -> None:
        result = await xero_void_credit_note(credit_note_id="cn-1", confirm=True)
        assert "Write operations are disabled" in result

    async def test_void_credit_note_blocked_confirm(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_void_credit_note(credit_note_id="cn-1", confirm=False)
        assert "confirm=true" in result

    async def test_void_credit_note_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.void_credit_note.return_value = {}
        result = await xero_void_credit_note(credit_note_id="cn-1", confirm=True)
        assert "voided" in result


# ===========================================================================
# Purchase Order tools
# ===========================================================================


class TestPurchaseOrderTools:
    async def test_purchase_orders_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_purchase_orders.return_value = {"PurchaseOrders": [SAMPLE_PURCHASE_ORDER]}
        result = await xero_purchase_orders()
        assert "PO-0001" in result

    async def test_create_purchase_order_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_purchase_order(
            contact_id="c-1",
            line_items='[{"Description":"Widget","Quantity":10,"UnitAmount":5}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_purchase_order_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_purchase_order.return_value = {"PurchaseOrders": [{"PurchaseOrderNumber": "PO-002"}]}
        result = await xero_create_purchase_order(
            contact_id="c-1",
            line_items='[{"Description":"Widget","Quantity":10,"UnitAmount":5}]',
        )
        assert "PO-002" in result

    async def test_create_purchase_order_invalid_json(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_create_purchase_order(contact_id="c-1", line_items="{bad")
        assert "must be valid JSON" in result


# ===========================================================================
# Quote tools
# ===========================================================================


class TestQuoteTools:
    async def test_quotes_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_quotes.return_value = {"Quotes": [SAMPLE_QUOTE]}
        result = await xero_quotes()
        assert "QU-0001" in result

    async def test_create_quote_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_quote(
            contact_id="c-1",
            line_items='[{"Description":"Service","Quantity":1,"UnitAmount":1000}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_quote_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_quote.return_value = {"Quotes": [{"QuoteNumber": "QU-002"}]}
        result = await xero_create_quote(
            contact_id="c-1",
            line_items='[{"Description":"Service","Quantity":1,"UnitAmount":1000}]',
            title="Project proposal",
            summary="Q1 2026 work",
        )
        assert "QU-002" in result


# ===========================================================================
# Account / Chart of Accounts tools
# ===========================================================================


class TestAccountTools:
    async def test_accounts_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_accounts.return_value = {"Accounts": [SAMPLE_ACCOUNT]}
        result = await xero_accounts()
        assert "Sales" in result

    async def test_accounts_with_type_filter(self, mock_client: AsyncMock) -> None:
        mock_client.list_accounts.return_value = {"Accounts": []}
        await xero_accounts(account_type="REVENUE")
        call_kwargs = mock_client.list_accounts.call_args[1]
        assert 'Type=="REVENUE"' in call_kwargs["where"]

    async def test_accounts_with_class_filter(self, mock_client: AsyncMock) -> None:
        mock_client.list_accounts.return_value = {"Accounts": []}
        await xero_accounts(account_class="ASSET")
        call_kwargs = mock_client.list_accounts.call_args[1]
        assert 'Class=="ASSET"' in call_kwargs["where"]

    async def test_account_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_account.return_value = {"Accounts": [SAMPLE_ACCOUNT]}
        result = await xero_account("acc-1")
        assert "Sales" in result


# ===========================================================================
# Manual Journal tools
# ===========================================================================


class TestManualJournalTools:
    async def test_manual_journals_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_manual_journals.return_value = {
            "ManualJournals": [
                {"ManualJournalID": "mj-1", "Narration": "Entry", "Status": "POSTED", "DateString": "2026-03-31"}
            ]
        }
        result = await xero_manual_journals()
        assert "Entry" in result


# ===========================================================================
# Report tools
# ===========================================================================


class TestReportTools:
    async def test_profit_loss(self, mock_client: AsyncMock) -> None:
        mock_client.get_profit_and_loss.return_value = SAMPLE_REPORT
        result = await xero_profit_loss(from_date="2026-03-01", to_date="2026-03-31")
        assert "Profit and Loss" in result

    async def test_balance_sheet(self, mock_client: AsyncMock) -> None:
        mock_client.get_balance_sheet.return_value = SAMPLE_REPORT
        result = await xero_balance_sheet(date="2026-03-31")
        assert "Profit and Loss" in result  # Same sample report

    async def test_trial_balance(self, mock_client: AsyncMock) -> None:
        mock_client.get_trial_balance.return_value = SAMPLE_REPORT
        result = await xero_trial_balance()
        assert "Report:" in result

    async def test_aged_receivables(self, mock_client: AsyncMock) -> None:
        mock_client.get_aged_receivables.return_value = SAMPLE_REPORT
        result = await xero_aged_receivables()
        assert "Report:" in result

    async def test_aged_payables(self, mock_client: AsyncMock) -> None:
        mock_client.get_aged_payables.return_value = SAMPLE_REPORT
        result = await xero_aged_payables()
        assert "Report:" in result


# ===========================================================================
# Reference data tools
# ===========================================================================


class TestReferenceDataTools:
    async def test_tax_rates(self, mock_client: AsyncMock) -> None:
        mock_client.list_tax_rates.return_value = {
            "TaxRates": [{"TaxType": "OUTPUT", "Name": "GST", "EffectiveRate": 10, "Status": "ACTIVE"}]
        }
        result = await xero_tax_rates()
        assert "GST" in result

    async def test_currencies(self, mock_client: AsyncMock) -> None:
        mock_client.list_currencies.return_value = {"Currencies": [{"Code": "AUD", "Description": "Australian Dollar"}]}
        result = await xero_currencies()
        assert "AUD" in result

    async def test_tracking_categories(self, mock_client: AsyncMock) -> None:
        mock_client.list_tracking_categories.return_value = {
            "TrackingCategories": [{"TrackingCategoryID": "tc-1", "Name": "Region", "Status": "ACTIVE", "Options": []}]
        }
        result = await xero_tracking_categories()
        assert "Region" in result

    async def test_branding_themes(self, mock_client: AsyncMock) -> None:
        mock_client.list_branding_themes.return_value = {
            "BrandingThemes": [{"BrandingThemeID": "bt-1", "Name": "Standard"}]
        }
        result = await xero_branding_themes()
        assert "Standard" in result


# ===========================================================================
# Payroll AU tools
# ===========================================================================


class TestPayrollTools:
    async def test_employees_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_employees.return_value = {"Employees": [SAMPLE_EMPLOYEE]}
        result = await xero_employees()
        assert "Jane Smith" in result

    async def test_employee_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_employee.return_value = {"Employees": [SAMPLE_EMPLOYEE]}
        result = await xero_employee("emp-1")
        assert "Jane Smith" in result

    async def test_timesheets_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_timesheets.return_value = {"Timesheets": [SAMPLE_TIMESHEET]}
        result = await xero_timesheets()
        assert "DRAFT" in result

    async def test_timesheet_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_timesheet.return_value = {"Timesheets": [SAMPLE_TIMESHEET]}
        result = await xero_timesheet("ts-1")
        assert "DRAFT" in result

    async def test_create_timesheet_blocked(self, mock_client: AsyncMock) -> None:
        result = await xero_create_timesheet(
            employee_id="emp-1",
            start_date="2026-03-25",
            end_date="2026-03-31",
            timesheet_lines='[{"EarningsRateID":"er-1","NumberOfUnits":[8,8,8,8,8,0,0]}]',
        )
        assert "Write operations are disabled" in result

    async def test_create_timesheet_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.create_timesheet.return_value = {"Timesheets": [SAMPLE_TIMESHEET]}
        result = await xero_create_timesheet(
            employee_id="emp-1",
            start_date="2026-03-25",
            end_date="2026-03-31",
            timesheet_lines='[{"EarningsRateID":"er-1","NumberOfUnits":[8,8,8,8,8,0,0]}]',
        )
        assert "DRAFT" in result

    async def test_create_timesheet_invalid_json(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_create_timesheet(
            employee_id="emp-1",
            start_date="2026-03-25",
            end_date="2026-03-31",
            timesheet_lines="bad",
        )
        assert "must be valid JSON" in result

    async def test_approve_timesheet_blocked_write(self, mock_client: AsyncMock) -> None:
        result = await xero_approve_timesheet(timesheet_id="ts-1", confirm=True)
        assert "Write operations are disabled" in result

    async def test_approve_timesheet_blocked_confirm(self, mock_client: AsyncMock, enable_writes: None) -> None:
        result = await xero_approve_timesheet(timesheet_id="ts-1", confirm=False)
        assert "confirm=true" in result

    async def test_approve_timesheet_success(self, mock_client: AsyncMock, enable_writes: None) -> None:
        mock_client.approve_timesheet.return_value = {}
        result = await xero_approve_timesheet(timesheet_id="ts-1", confirm=True)
        assert "approved" in result

    async def test_payslips_list(self, mock_client: AsyncMock) -> None:
        mock_client.list_payslips.return_value = {
            "PayRuns": [
                {
                    "Payslips": [
                        {"PayslipID": "ps-1", "EmployeeID": "emp-1", "FirstName": "J", "LastName": "S", "NetPay": 3000}
                    ]
                }
            ]
        }
        result = await xero_payslips(payrun_id="pr-1")
        assert "ps-1" in result

    async def test_payslip_detail(self, mock_client: AsyncMock) -> None:
        mock_client.get_payslip.return_value = {"Payslip": SAMPLE_PAYSLIP}
        result = await xero_payslip("ps-1")
        assert "Jane Smith" in result


# ===========================================================================
# Webhook verification tool
# ===========================================================================


class TestWebhookVerification:
    def _compute_signature(self, key: str, body: str) -> str:
        """Compute HMAC-SHA256 signature the way Xero does."""
        digest = hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    async def test_no_webhook_key(self) -> None:
        result = await xero_verify_webhook(
            raw_body='{"events":[]}',
            signature_header="abc",
        )
        assert "XERO_WEBHOOK_KEY not configured" in result

    async def test_valid_signature(self, set_webhook_key: str) -> None:
        body = '{"events": [{"eventType": "CREATE"}, {"eventType": "UPDATE"}]}'
        sig = self._compute_signature(set_webhook_key, body)
        result = await xero_verify_webhook(raw_body=body, signature_header=sig)
        assert "Valid webhook" in result
        assert "2" in result  # event_count

    async def test_invalid_signature(self, set_webhook_key: str) -> None:
        body = '{"events": [{"eventType": "CREATE"}]}'
        result = await xero_verify_webhook(raw_body=body, signature_header="badsignature")
        assert "Invalid webhook" in result
        assert "Signature mismatch" in result

    async def test_tampered_body(self, set_webhook_key: str) -> None:
        original = '{"events": [{"eventType": "CREATE"}]}'
        sig = self._compute_signature(set_webhook_key, original)
        tampered = '{"events": [{"eventType": "DELETE"}]}'
        result = await xero_verify_webhook(raw_body=tampered, signature_header=sig)
        assert "Invalid webhook" in result

    async def test_invalid_json_body(self, set_webhook_key: str) -> None:
        body = "not valid json"
        sig = self._compute_signature(set_webhook_key, body)
        result = await xero_verify_webhook(raw_body=body, signature_header=sig)
        # The HMAC matches but JSON parsing fails
        assert "Invalid webhook" in result

    async def test_empty_events(self, set_webhook_key: str) -> None:
        body = '{"events": []}'
        sig = self._compute_signature(set_webhook_key, body)
        result = await xero_verify_webhook(raw_body=body, signature_header=sig)
        assert "Valid webhook" in result
        assert "0" in result


# ===========================================================================
# Write gate integration across all write tools
# ===========================================================================


class TestWriteGateIntegration:
    """Verify every write tool is properly gated."""

    @pytest.mark.parametrize(
        "tool_fn,kwargs",
        [
            (xero_create_contact, {"name": "Test"}),
            (xero_update_contact, {"contact_id": "c-1", "name": "New"}),
            (xero_archive_contact, {"contact_id": "c-1", "confirm": True}),
            (xero_create_invoice, {"contact_id": "c-1", "line_items": "[]"}),
            (xero_update_invoice, {"invoice_id": "i-1", "reference": "ref"}),
            (xero_void_invoice, {"invoice_id": "i-1", "confirm": True}),
            (xero_email_invoice, {"invoice_id": "i-1"}),
            (xero_create_bill, {"contact_id": "c-1", "line_items": "[]"}),
            (xero_void_bill, {"bill_id": "b-1", "confirm": True}),
            (
                xero_create_bank_transaction,
                {
                    "txn_type": "SPEND",
                    "contact_id": "c-1",
                    "bank_account_id": "ba-1",
                    "line_items": "[]",
                },
            ),
            (xero_create_payment, {"invoice_id": "i-1", "account_id": "a-1", "amount": 100.0}),
            (xero_delete_payment, {"payment_id": "p-1", "confirm": True}),
            (xero_create_credit_note, {"contact_id": "c-1", "line_items": "[]"}),
            (xero_void_credit_note, {"credit_note_id": "cn-1", "confirm": True}),
            (xero_create_purchase_order, {"contact_id": "c-1", "line_items": "[]"}),
            (xero_create_quote, {"contact_id": "c-1", "line_items": "[]"}),
            (
                xero_create_timesheet,
                {
                    "employee_id": "e-1",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-07",
                    "timesheet_lines": "[]",
                },
            ),
            (xero_approve_timesheet, {"timesheet_id": "ts-1", "confirm": True}),
        ],
    )
    async def test_all_write_tools_blocked(self, mock_client: AsyncMock, tool_fn: Any, kwargs: dict[str, Any]) -> None:
        result = await tool_fn(**kwargs)
        assert "Write operations are disabled" in result


# ===========================================================================
# Confirm gate integration across all destructive tools
# ===========================================================================


class TestConfirmGateIntegration:
    """Verify destructive operations require confirm=true."""

    @pytest.mark.parametrize(
        "tool_fn,kwargs",
        [
            (xero_archive_contact, {"contact_id": "c-1"}),
            (xero_void_invoice, {"invoice_id": "i-1"}),
            (xero_void_bill, {"bill_id": "b-1"}),
            (xero_delete_payment, {"payment_id": "p-1"}),
            (xero_void_credit_note, {"credit_note_id": "cn-1"}),
            (xero_approve_timesheet, {"timesheet_id": "ts-1"}),
        ],
    )
    async def test_all_destructive_tools_require_confirm(
        self,
        mock_client: AsyncMock,
        enable_writes: None,
        tool_fn: Any,
        kwargs: dict[str, Any],
    ) -> None:
        # Default confirm=False
        result = await tool_fn(**kwargs)
        assert "confirm=true" in result
