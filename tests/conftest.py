"""Shared fixtures for xero-blade-mcp tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Xero env vars so tests start from a clean slate."""
    for var in (
        "XERO_ACCESS_TOKEN",
        "XERO_CLIENT_ID",
        "XERO_CLIENT_SECRET",
        "XERO_TENANT_ID",
        "XERO_WRITE_ENABLED",
        "XERO_WEBHOOK_KEY",
        "XERO_MCP_TRANSPORT",
        "XERO_MCP_HOST",
        "XERO_MCP_PORT",
        "XERO_MCP_API_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def enable_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable write operations."""
    monkeypatch.setenv("XERO_WRITE_ENABLED", "true")


@pytest.fixture
def set_webhook_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a deterministic webhook key and return it."""
    key = "test-webhook-key-12345"
    monkeypatch.setenv("XERO_WEBHOOK_KEY", key)
    return key


@pytest.fixture
def set_static_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a static access token."""
    token = "xero-test-access-token-abc123"
    monkeypatch.setenv("XERO_ACCESS_TOKEN", token)
    return token


@pytest.fixture
def set_client_credentials(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Set client ID and secret for Custom Connection auth."""
    client_id = "test-client-id"
    client_secret = "test-client-secret"
    monkeypatch.setenv("XERO_CLIENT_ID", client_id)
    monkeypatch.setenv("XERO_CLIENT_SECRET", client_secret)
    return client_id, client_secret


@pytest.fixture
def set_tenant(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a tenant ID."""
    tenant_id = "abc12345-def6-7890-abcd-ef1234567890"
    monkeypatch.setenv("XERO_TENANT_ID", tenant_id)
    return tenant_id


# ---------------------------------------------------------------------------
# Mock response factory
# ---------------------------------------------------------------------------


def make_response(
    status_code: int = 200,
    json_data: Any = None,
    text: str = "",
    headers: dict[str, str] | None = None,
    content: bytes = b"",
    content_type: str = "application/json",
) -> AsyncMock:
    """Create a mock httpx.Response."""
    mock = AsyncMock()
    mock.status_code = status_code
    mock.is_success = 200 <= status_code < 300
    mock.text = text or (json.dumps(json_data) if json_data else "")
    mock.content = content or mock.text.encode()
    mock.headers = {"content-type": content_type, **(headers or {})}

    def _json() -> Any:
        if json_data is not None:
            return json_data
        return json.loads(mock.text)

    mock.json = _json
    return mock


# ---------------------------------------------------------------------------
# Sample Xero API response data
# ---------------------------------------------------------------------------

SAMPLE_CONTACT = {
    "ContactID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "Name": "Acme Corporation",
    "ContactStatus": "ACTIVE",
    "EmailAddress": "billing@acme.com",
    "FirstName": "John",
    "LastName": "Doe",
    "IsCustomer": True,
    "IsSupplier": False,
    "DefaultCurrency": "AUD",
    "TaxNumber": "12345678901",
    "AccountNumber": "ACC-001",
    "Phones": [
        {"PhoneType": "DEFAULT", "PhoneNumber": "5551234", "PhoneAreaCode": "02", "PhoneCountryCode": "61"},
    ],
    "Addresses": [
        {
            "AddressType": "STREET",
            "AddressLine1": "123 Main St",
            "City": "Sydney",
            "Region": "NSW",
            "PostalCode": "2000",
            "Country": "Australia",
        }
    ],
    "Balances": {
        "AccountsReceivable": {"Outstanding": "1500.00"},
        "AccountsPayable": {"Outstanding": "0.00"},
    },
}

SAMPLE_INVOICE = {
    "InvoiceID": "inv-12345678-abcd-ef12-3456-7890abcdef01",
    "InvoiceNumber": "INV-0001",
    "Type": "ACCREC",
    "Status": "AUTHORISED",
    "CurrencyCode": "AUD",
    "Contact": {"Name": "Acme Corporation", "ContactID": "c-123"},
    "DateString": "2026-03-15",
    "DueDateString": "2026-04-15",
    "Reference": "PO-123",
    "SubTotal": "1000.00",
    "TotalTax": "100.00",
    "Total": "1100.00",
    "AmountDue": "1100.00",
    "AmountPaid": "0.00",
    "LineItems": [
        {
            "Description": "Consulting services",
            "Quantity": 10,
            "UnitAmount": 100.00,
            "LineAmount": "1000.00",
            "AccountCode": "200",
        }
    ],
    "Payments": [],
    "UpdatedDateUTC": "/Date(1711000000000+0000)/",
}

SAMPLE_BILL = {
    **SAMPLE_INVOICE,
    "InvoiceID": "bill-12345678-abcd-ef12-3456-7890abcdef01",
    "InvoiceNumber": "BILL-0001",
    "Type": "ACCPAY",
    "Contact": {"Name": "Supplier Co", "ContactID": "s-456"},
}

SAMPLE_BANK_TRANSACTION = {
    "BankTransactionID": "bt-12345678-abcd-ef12-3456-7890abcdef01",
    "Type": "SPEND",
    "Contact": {"Name": "Office Supplies Ltd"},
    "CurrencyCode": "AUD",
    "Status": "AUTHORISED",
    "DateString": "2026-03-20",
    "Total": "250.00",
    "SubTotal": "227.27",
    "BankAccount": {"Name": "Business Cheque", "AccountID": "ba-123"},
    "Reference": "REF-001",
    "LineItems": [
        {"Description": "Printer paper", "LineAmount": "227.27"},
    ],
}

SAMPLE_PAYMENT = {
    "PaymentID": "pay-12345678-abcd-ef12-3456-7890abcdef01",
    "Amount": "500.00",
    "CurrencyCode": "AUD",
    "Status": "AUTHORISED",
    "Date": "/Date(1711000000000+0000)/",
    "PaymentType": "ACCRECPAYMENT",
    "Reference": "PAY-001",
    "Invoice": {"InvoiceID": "inv-123", "InvoiceNumber": "INV-0001"},
    "Account": {"Name": "Business Cheque"},
}

SAMPLE_CREDIT_NOTE = {
    "CreditNoteID": "cn-12345678-abcd-ef12-3456-7890abcdef01",
    "CreditNoteNumber": "CN-0001",
    "Contact": {"Name": "Acme Corporation"},
    "CurrencyCode": "AUD",
    "Status": "AUTHORISED",
    "Total": "200.00",
    "DateString": "2026-03-18",
    "RemainingCredit": "200.00",
}

SAMPLE_PURCHASE_ORDER = {
    "PurchaseOrderID": "po-12345678-abcd-ef12-3456-7890abcdef01",
    "PurchaseOrderNumber": "PO-0001",
    "Contact": {"Name": "Supplier Co"},
    "CurrencyCode": "AUD",
    "Status": "AUTHORISED",
    "Total": "750.00",
    "DateString": "2026-03-10",
}

SAMPLE_QUOTE = {
    "QuoteID": "q-12345678-abcd-ef12-3456-7890abcdef01",
    "QuoteNumber": "QU-0001",
    "Contact": {"Name": "Prospect Inc"},
    "CurrencyCode": "AUD",
    "Status": "SENT",
    "Total": "3000.00",
    "DateString": "2026-03-25",
}

SAMPLE_ACCOUNT = {
    "AccountID": "acc-12345678-abcd-ef12-3456-7890abcdef01",
    "Code": "200",
    "Name": "Sales",
    "Type": "REVENUE",
    "Class": "REVENUE",
    "Status": "ACTIVE",
    "TaxType": "OUTPUT",
    "Description": "Income from sales",
    "BankAccountType": "",
    "CurrencyCode": "AUD",
    "EnablePaymentsToAccount": False,
}

SAMPLE_EMPLOYEE = {
    "EmployeeID": "emp-12345678-abcd-ef12-3456-7890abcdef01",
    "FirstName": "Jane",
    "LastName": "Smith",
    "Status": "ACTIVE",
    "Email": "jane.smith@example.com",
    "DateOfBirth": "/Date(631152000000+0000)/",
    "StartDate": "/Date(1704067200000+0000)/",
    "TerminationDate": None,
    "JobTitle": "Developer",
    "Classification": "Full-Time",
    "OrdinaryEarningsRateID": "er-123",
    "HomeAddress": {
        "AddressLine1": "456 Oak Ave",
        "City": "Melbourne",
        "Region": "VIC",
        "PostalCode": "3000",
    },
    "TaxDeclaration": {
        "TFNPendingOrExemptionHeld": False,
        "TaxFreeThresholdClaimed": True,
    },
    "SuperMemberships": [
        {"SuperFundID": "sf-12345678", "EmployeeNumber": "EMP001"},
    ],
}

SAMPLE_TIMESHEET = {
    "TimesheetID": "ts-12345678-abcd-ef12-3456-7890abcdef01",
    "EmployeeID": "emp-12345678-abcd-ef12-3456-7890abcdef01",
    "Status": "DRAFT",
    "StartDate": "/Date(1711065600000+0000)/",
    "EndDate": "/Date(1711584000000+0000)/",
    "Hours": 40.0,
    "TimesheetLines": [
        {
            "EarningsRateID": "er-12345678",
            "NumberOfUnits": [8, 8, 8, 8, 8, 0, 0],
        }
    ],
}

SAMPLE_PAYSLIP = {
    "PayslipID": "ps-12345678-abcd-ef12-3456-7890abcdef01",
    "EmployeeID": "emp-12345678",
    "FirstName": "Jane",
    "LastName": "Smith",
    "NetPay": 3500.00,
    "Tax": 850.00,
    "Super": 420.00,
    "EarningsLines": [
        {"EarningsRateID": "er-12345678", "NumberOfUnits": 38, "Amount": 4200.00},
    ],
    "DeductionLines": [
        {"DeductionTypeID": "dt-12345678", "Amount": 50.00},
    ],
    "SuperannuationLines": [
        {"SuperMembershipID": "sm-12345678", "Amount": 420.00},
    ],
}

SAMPLE_REPORT = {
    "Reports": [
        {
            "ReportName": "Profit and Loss",
            "ReportDate": "1 March 2026 to 31 March 2026",
            "Rows": [
                {
                    "RowType": "Header",
                    "Cells": [
                        {"Value": ""},
                        {"Value": "March 2026"},
                    ],
                },
                {
                    "RowType": "Section",
                    "Title": "Revenue",
                    "Rows": [
                        {"Cells": [{"Value": "Sales"}, {"Value": "10000.00"}]},
                        {"Cells": [{"Value": "Other Revenue"}, {"Value": "500.00"}]},
                    ],
                },
                {
                    "RowType": "SummaryRow",
                    "Cells": [
                        {"Value": "Total Revenue"},
                        {"Value": "10500.00"},
                    ],
                },
            ],
        }
    ]
}

SAMPLE_ORGANISATION = {
    "Organisations": [
        {
            "Name": "Test Company Pty Ltd",
            "LegalName": "Test Company Pty Limited",
            "ShortCode": "TST",
            "CountryCode": "AU",
            "BaseCurrency": "AUD",
            "OrganisationType": "COMPANY",
            "Class": "PREMIUM",
            "Version": "AU",
            "TaxNumber": "12345678901",
            "FinancialYearEndDay": 30,
            "FinancialYearEndMonth": 6,
            "SalesTaxBasis": "ACCRUALS",
            "SalesTaxPeriod": "QUARTERLY",
            "Timezone": "AUSEASTERNSTANDARDTIME",
        }
    ]
}

SAMPLE_CONNECTION = {
    "tenantId": "abc12345-def6-7890-abcd-ef1234567890",
    "tenantName": "Test Company Pty Ltd",
    "tenantType": "ORGANISATION",
}
