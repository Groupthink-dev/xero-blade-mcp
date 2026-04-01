"""Tests for xero_blade_mcp.formatters — all formatters with realistic Xero shapes."""

from __future__ import annotations

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
    format_datetime_short,
    format_employee_detail,
    format_employee_list,
    format_invoice_detail,
    format_invoice_list,
    format_manual_journal_list,
    format_organisation_detail,
    format_page_hint,
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
    format_xero_date,
    select_fields,
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

# ===========================================================================
# Date helpers
# ===========================================================================


class TestFormatXeroDate:
    def test_none_returns_question_mark(self) -> None:
        assert format_xero_date(None) == "?"

    def test_empty_string_returns_question_mark(self) -> None:
        assert format_xero_date("") == "?"

    def test_iso_date(self) -> None:
        assert format_xero_date("2026-03-15T14:30:00") == "2026-03-15"

    def test_iso_date_with_tz(self) -> None:
        assert format_xero_date("2026-03-15T14:30:00+11:00") == "2026-03-15"

    def test_dotnet_date_format(self) -> None:
        # /Date(1711000000000+0000)/ -> 2024-03-21 (approximately)
        result = format_xero_date("/Date(1711000000000+0000)/")
        assert result.startswith("2024-03-")

    def test_dotnet_date_negative_offset(self) -> None:
        result = format_xero_date("/Date(1711000000000-0500)/")
        assert result.startswith("2024-03-")

    def test_dotnet_date_no_offset(self) -> None:
        result = format_xero_date("/Date(1711000000000)/")
        assert result.startswith("2024-03-")

    def test_plain_date_string(self) -> None:
        assert format_xero_date("2026-03-15") == "2026-03-15"

    def test_dotnet_date_epoch_zero(self) -> None:
        result = format_xero_date("/Date(0+0000)/")
        assert result == "1970-01-01"

    def test_invalid_dotnet_date_returns_original(self) -> None:
        result = format_xero_date("/Date(notanumber+0000)/")
        assert "/Date(" in result


class TestFormatDatetimeShort:
    def test_none_returns_question_mark(self) -> None:
        assert format_datetime_short(None) == "?"

    def test_empty_returns_question_mark(self) -> None:
        assert format_datetime_short("") == "?"

    def test_iso_datetime(self) -> None:
        assert format_datetime_short("2026-03-15T14:30:00") == "2026-03-15 14:30"

    def test_iso_datetime_with_z(self) -> None:
        assert format_datetime_short("2026-03-15T14:30:00Z") == "2026-03-15 14:30"

    def test_iso_datetime_with_utc_offset(self) -> None:
        assert format_datetime_short("2026-03-15T14:30:00+00:00") == "2026-03-15 14:30"

    def test_dotnet_date_falls_through(self) -> None:
        result = format_datetime_short("/Date(1711000000000+0000)/")
        assert result.startswith("2024-03-")


# ===========================================================================
# Field selection
# ===========================================================================


class TestSelectFields:
    def test_no_fields_returns_all(self) -> None:
        data = {"Name": "Acme", "Email": "a@b.com", "Phone": "123"}
        assert select_fields(data, None) == data

    def test_filters_to_requested(self) -> None:
        data = {"ContactID": "c-1", "Name": "Acme", "Email": "a@b.com", "Phone": "123"}
        result = select_fields(data, "Name,Email")
        assert result == {"ContactID": "c-1", "Name": "Acme", "Email": "a@b.com"}

    def test_always_includes_id_fields(self) -> None:
        data = {"InvoiceID": "inv-1", "Total": "100", "Status": "PAID"}
        result = select_fields(data, "Status")
        assert "InvoiceID" in result
        assert "Status" in result
        assert "Total" not in result

    def test_handles_spaces_in_fields(self) -> None:
        data = {"ContactID": "c-1", "Name": "Acme", "Email": "a@b.com"}
        result = select_fields(data, "Name, Email")
        assert "Name" in result
        assert "Email" in result

    def test_missing_field_ignored(self) -> None:
        data = {"ContactID": "c-1", "Name": "Acme"}
        result = select_fields(data, "Name,Nonexistent")
        assert result == {"ContactID": "c-1", "Name": "Acme"}


# ===========================================================================
# Pagination
# ===========================================================================


class TestFormatPageHint:
    def test_full_page_shows_hint(self) -> None:
        hint = format_page_hint(100, 1)
        assert "page=2" in hint

    def test_partial_page_no_hint(self) -> None:
        assert format_page_hint(50, 1) == ""

    def test_empty_page_no_hint(self) -> None:
        assert format_page_hint(0, 1) == ""

    def test_page_2_suggests_page_3(self) -> None:
        hint = format_page_hint(100, 2)
        assert "page=3" in hint

    def test_custom_page_size(self) -> None:
        hint = format_page_hint(50, 1, page_size=50)
        assert "page=2" in hint


# ===========================================================================
# Connection / Organisation formatters
# ===========================================================================


class TestFormatConnectionList:
    def test_empty_connections(self) -> None:
        assert format_connection_list([]) == "No connected organisations."

    def test_single_connection(self) -> None:
        result = format_connection_list([SAMPLE_CONNECTION])
        assert "abc12345" in result
        assert "Test Company" in result
        assert "ORGANISATION" in result

    def test_multiple_connections(self) -> None:
        connections = [
            SAMPLE_CONNECTION,
            {"tenantId": "xyz-789", "tenantName": "Other Co", "tenantType": "ORGANISATION"},
        ]
        result = format_connection_list(connections)
        lines = result.strip().split("\n")
        assert len(lines) == 2


class TestFormatOrganisationDetail:
    def test_formats_org(self) -> None:
        result = format_organisation_detail(SAMPLE_ORGANISATION)
        assert "Test Company Pty Ltd" in result
        assert "AU" in result
        assert "AUD" in result
        assert "COMPANY" in result
        assert "PREMIUM" in result

    def test_empty_organisations(self) -> None:
        assert format_organisation_detail({"Organisations": []}) == "No organisation data."

    def test_financial_year_end(self) -> None:
        result = format_organisation_detail(SAMPLE_ORGANISATION)
        assert "30/6" in result


# ===========================================================================
# Contact formatters
# ===========================================================================


class TestFormatContactList:
    def test_empty_contacts(self) -> None:
        assert format_contact_list({"Contacts": []}) == "No contacts found."

    def test_single_contact(self) -> None:
        result = format_contact_list({"Contacts": [SAMPLE_CONTACT]})
        assert "a1b2c3d4" in result
        assert "Acme Corporation" in result
        assert "ACTIVE" in result
        assert "billing@acme.com" in result
        assert "customer" in result

    def test_supplier_role(self) -> None:
        contact = {**SAMPLE_CONTACT, "IsCustomer": False, "IsSupplier": True}
        result = format_contact_list({"Contacts": [contact]})
        assert "supplier" in result
        assert "customer" not in result

    def test_customer_and_supplier(self) -> None:
        contact = {**SAMPLE_CONTACT, "IsCustomer": True, "IsSupplier": True}
        result = format_contact_list({"Contacts": [contact]})
        assert "customer+supplier" in result

    def test_no_email_omitted(self) -> None:
        contact = {**SAMPLE_CONTACT}
        del contact["EmailAddress"]
        result = format_contact_list({"Contacts": [contact]})
        assert "@" not in result

    def test_pagination_hint(self) -> None:
        contacts = [SAMPLE_CONTACT] * 100
        result = format_contact_list({"Contacts": contacts}, page=1)
        assert "page=2" in result

    def test_no_pagination_hint_partial_page(self) -> None:
        contacts = [SAMPLE_CONTACT] * 50
        result = format_contact_list({"Contacts": contacts}, page=1)
        assert "page=" not in result


class TestFormatContactDetail:
    def test_full_contact(self) -> None:
        result = format_contact_detail({"Contacts": [SAMPLE_CONTACT]})
        assert "Acme Corporation" in result
        assert "ACTIVE" in result
        assert "billing@acme.com" in result
        assert "John" in result
        assert "Doe" in result
        assert "12345678901" in result
        assert "ACC-001" in result
        assert "AUD" in result

    def test_phone_formatting(self) -> None:
        result = format_contact_detail({"Contacts": [SAMPLE_CONTACT]})
        assert "+61" in result
        assert "(02)" in result
        assert "5551234" in result

    def test_address_formatting(self) -> None:
        result = format_contact_detail({"Contacts": [SAMPLE_CONTACT]})
        assert "123 Main St" in result
        assert "Sydney" in result
        assert "STREET" in result

    def test_balances(self) -> None:
        result = format_contact_detail({"Contacts": [SAMPLE_CONTACT]})
        assert "1500.00" in result

    def test_field_selection(self) -> None:
        result = format_contact_detail({"Contacts": [SAMPLE_CONTACT]}, fields="Name,ContactStatus")
        assert "Acme Corporation" in result
        assert "ACTIVE" in result

    def test_contact_without_wrapper(self) -> None:
        result = format_contact_detail(SAMPLE_CONTACT)
        assert "Acme Corporation" in result


# ===========================================================================
# Invoice formatters
# ===========================================================================


class TestFormatInvoiceList:
    def test_empty_invoices(self) -> None:
        assert format_invoice_list({"Invoices": []}) == "No invoices found."

    def test_empty_bills(self) -> None:
        assert format_invoice_list({"Invoices": []}, label="bills") == "No bills found."

    def test_single_invoice(self) -> None:
        result = format_invoice_list({"Invoices": [SAMPLE_INVOICE]})
        assert "INV-0001" in result
        assert "Acme Corporation" in result
        assert "AUTHORISED" in result
        assert "A$1,100.00 AUD" in result

    def test_due_amount_shown(self) -> None:
        result = format_invoice_list({"Invoices": [SAMPLE_INVOICE]})
        assert "due=" in result

    def test_paid_invoice_no_due(self) -> None:
        paid = {**SAMPLE_INVOICE, "Status": "PAID", "AmountDue": "0.00"}
        result = format_invoice_list({"Invoices": [paid]})
        assert "due=" not in result

    def test_voided_invoice_no_due(self) -> None:
        voided = {**SAMPLE_INVOICE, "Status": "VOIDED", "AmountDue": "1100.00"}
        result = format_invoice_list({"Invoices": [voided]})
        assert "due=" not in result

    def test_pagination(self) -> None:
        invoices = [SAMPLE_INVOICE] * 100
        result = format_invoice_list({"Invoices": invoices}, page=1)
        assert "page=2" in result


class TestFormatInvoiceDetail:
    def test_full_invoice(self) -> None:
        result = format_invoice_detail({"Invoices": [SAMPLE_INVOICE]})
        assert "INV-0001" in result
        assert "Sales Invoice" in result
        assert "AUTHORISED" in result
        assert "Acme Corporation" in result
        assert "PO-123" in result
        assert "A$1,000.00 AUD" in result  # Subtotal
        assert "A$100.00 AUD" in result  # Tax
        assert "A$1,100.00 AUD" in result  # Total

    def test_line_items(self) -> None:
        result = format_invoice_detail({"Invoices": [SAMPLE_INVOICE]})
        assert "Consulting services" in result
        assert "qty=10" in result
        assert "Line Items (1)" in result

    def test_bill_type_label(self) -> None:
        bill = {**SAMPLE_INVOICE, "Type": "ACCPAY"}
        result = format_invoice_detail({"Invoices": [bill]})
        assert "Bill" in result

    def test_zero_tax_not_shown(self) -> None:
        inv = {**SAMPLE_INVOICE, "TotalTax": "0"}
        result = format_invoice_detail({"Invoices": [inv]})
        assert "Tax:" not in result

    def test_payments_shown(self) -> None:
        inv = {
            **SAMPLE_INVOICE,
            "Payments": [
                {"PaymentID": "pay-12345678", "Amount": "500.00", "Date": "/Date(1711000000000+0000)/"},
            ],
        }
        result = format_invoice_detail({"Invoices": [inv]})
        assert "Payments (1)" in result
        assert "pay-1234" in result

    def test_many_line_items_truncated(self) -> None:
        item_tmpl = {"Quantity": 1, "UnitAmount": 10, "LineAmount": "10.00"}
        items = [{"Description": f"Item {i}", **item_tmpl} for i in range(15)]
        inv = {**SAMPLE_INVOICE, "LineItems": items}
        result = format_invoice_detail({"Invoices": [inv]})
        assert "+5 more" in result

    def test_field_selection(self) -> None:
        result = format_invoice_detail({"Invoices": [SAMPLE_INVOICE]}, fields="InvoiceNumber,Status")
        assert "INV-0001" in result

    def test_updated_date(self) -> None:
        result = format_invoice_detail({"Invoices": [SAMPLE_INVOICE]})
        assert "Updated:" in result


# ===========================================================================
# Bank Transaction formatters
# ===========================================================================


class TestFormatBankTransactionList:
    def test_empty(self) -> None:
        assert format_bank_transaction_list({"BankTransactions": []}) == "No bank transactions found."

    def test_single_transaction(self) -> None:
        result = format_bank_transaction_list({"BankTransactions": [SAMPLE_BANK_TRANSACTION]})
        assert "bt-12345" in result
        assert "SPEND" in result
        assert "Office Supplies" in result
        assert "A$250.00 AUD" in result
        assert "AUTHORISED" in result

    def test_pagination(self) -> None:
        txns = [SAMPLE_BANK_TRANSACTION] * 100
        result = format_bank_transaction_list({"BankTransactions": txns}, page=2)
        assert "page=3" in result


class TestFormatBankTransactionDetail:
    def test_full_detail(self) -> None:
        result = format_bank_transaction_detail({"BankTransactions": [SAMPLE_BANK_TRANSACTION]})
        assert "SPEND" in result
        assert "Office Supplies" in result
        assert "Business Cheque" in result
        assert "REF-001" in result
        assert "Printer paper" in result

    def test_field_selection(self) -> None:
        result = format_bank_transaction_detail(
            {"BankTransactions": [SAMPLE_BANK_TRANSACTION]},
            fields="Type,Status",
        )
        assert "SPEND" in result


# ===========================================================================
# Payment formatters
# ===========================================================================


class TestFormatPaymentList:
    def test_empty(self) -> None:
        assert format_payment_list({"Payments": []}) == "No payments found."

    def test_single_payment(self) -> None:
        result = format_payment_list({"Payments": [SAMPLE_PAYMENT]})
        assert "pay-1234" in result
        assert "A$500.00 AUD" in result
        assert "AUTHORISED" in result
        assert "inv=INV-0001" in result

    def test_payment_without_invoice_number(self) -> None:
        p = {**SAMPLE_PAYMENT, "Invoice": {"InvoiceID": "inv-123"}}
        result = format_payment_list({"Payments": [p]})
        assert "inv=" not in result


class TestFormatPaymentDetail:
    def test_full_detail(self) -> None:
        result = format_payment_detail({"Payments": [SAMPLE_PAYMENT]})
        assert "A$500.00 AUD" in result
        assert "AUTHORISED" in result
        assert "ACCRECPAYMENT" in result
        assert "PAY-001" in result
        assert "INV-0001" in result
        assert "Business Cheque" in result


# ===========================================================================
# Credit Note formatters
# ===========================================================================


class TestFormatCreditNoteList:
    def test_empty(self) -> None:
        assert format_credit_note_list({"CreditNotes": []}) == "No credit notes found."

    def test_single_credit_note(self) -> None:
        result = format_credit_note_list({"CreditNotes": [SAMPLE_CREDIT_NOTE]})
        assert "CN-0001" in result
        assert "Acme Corporation" in result
        assert "AUTHORISED" in result
        assert "A$200.00 AUD" in result
        assert "remaining=" in result

    def test_no_remaining_credit(self) -> None:
        cn = {**SAMPLE_CREDIT_NOTE, "RemainingCredit": "0.00"}
        result = format_credit_note_list({"CreditNotes": [cn]})
        assert "remaining=" not in result


# ===========================================================================
# Purchase Order formatters
# ===========================================================================


class TestFormatPurchaseOrderList:
    def test_empty(self) -> None:
        assert format_purchase_order_list({"PurchaseOrders": []}) == "No purchase orders found."

    def test_single_po(self) -> None:
        result = format_purchase_order_list({"PurchaseOrders": [SAMPLE_PURCHASE_ORDER]})
        assert "PO-0001" in result
        assert "Supplier Co" in result
        assert "A$750.00 AUD" in result


# ===========================================================================
# Quote formatters
# ===========================================================================


class TestFormatQuoteList:
    def test_empty(self) -> None:
        assert format_quote_list({"Quotes": []}) == "No quotes found."

    def test_single_quote(self) -> None:
        result = format_quote_list({"Quotes": [SAMPLE_QUOTE]})
        assert "QU-0001" in result
        assert "Prospect Inc" in result
        assert "SENT" in result
        assert "A$3,000.00 AUD" in result


# ===========================================================================
# Account formatters
# ===========================================================================


class TestFormatAccountList:
    def test_empty(self) -> None:
        assert format_account_list({"Accounts": []}) == "No accounts found."

    def test_single_account(self) -> None:
        result = format_account_list({"Accounts": [SAMPLE_ACCOUNT]})
        assert "200" in result
        assert "Sales" in result
        assert "REVENUE" in result
        assert "ACTIVE" in result
        assert "tax=OUTPUT" in result

    def test_no_tax_type(self) -> None:
        acct = {**SAMPLE_ACCOUNT}
        del acct["TaxType"]
        result = format_account_list({"Accounts": [acct]})
        assert "tax=" not in result


class TestFormatAccountDetail:
    def test_full_detail(self) -> None:
        result = format_account_detail({"Accounts": [SAMPLE_ACCOUNT]})
        assert "200" in result
        assert "Sales" in result
        assert "REVENUE" in result
        assert "OUTPUT" in result
        assert "Income from sales" in result


# ===========================================================================
# Report formatters
# ===========================================================================


class TestFormatReport:
    def test_empty_report(self) -> None:
        assert format_report({"Reports": []}) == "No report data."

    def test_profit_and_loss(self) -> None:
        result = format_report(SAMPLE_REPORT)
        assert "Profit and Loss" in result
        assert "March 2026" in result
        assert "Revenue" in result
        assert "Sales" in result
        assert "10000.00" in result
        assert "500.00" in result
        assert "Total Revenue" in result

    def test_header_row(self) -> None:
        result = format_report(SAMPLE_REPORT)
        assert "March 2026" in result
        assert "---" in result  # Separator line

    def test_summary_row_bold(self) -> None:
        result = format_report(SAMPLE_REPORT)
        assert "**Total Revenue" in result

    def test_section_without_title(self) -> None:
        report = {
            "Reports": [
                {
                    "ReportName": "Test",
                    "ReportDate": "2026-03-31",
                    "Rows": [
                        {
                            "RowType": "Section",
                            "Title": "",
                            "Rows": [
                                {"Cells": [{"Value": "Item"}, {"Value": "100"}]},
                            ],
                        }
                    ],
                }
            ]
        }
        result = format_report(report)
        assert "Item" in result


# ===========================================================================
# Tax / Currency / Tracking formatters
# ===========================================================================


class TestFormatTaxRateList:
    def test_empty(self) -> None:
        assert format_tax_rate_list({"TaxRates": []}) == "No tax rates found."

    def test_single_rate(self) -> None:
        result = format_tax_rate_list(
            {
                "TaxRates": [
                    {"TaxType": "OUTPUT", "Name": "GST on Income", "EffectiveRate": 10, "Status": "ACTIVE"},
                ]
            }
        )
        assert "OUTPUT" in result
        assert "GST on Income" in result
        assert "10%" in result
        assert "ACTIVE" in result


class TestFormatCurrencyList:
    def test_empty(self) -> None:
        assert format_currency_list({"Currencies": []}) == "No currencies found."

    def test_single_currency(self) -> None:
        result = format_currency_list({"Currencies": [{"Code": "AUD", "Description": "Australian Dollar"}]})
        assert "AUD" in result
        assert "Australian Dollar" in result


class TestFormatTrackingCategoryList:
    def test_empty(self) -> None:
        assert format_tracking_category_list({"TrackingCategories": []}) == "No tracking categories found."

    def test_with_options(self) -> None:
        result = format_tracking_category_list(
            {
                "TrackingCategories": [
                    {
                        "TrackingCategoryID": "tc-12345678-abcd",
                        "Name": "Region",
                        "Status": "ACTIVE",
                        "Options": [
                            {"Name": "North"},
                            {"Name": "South"},
                            {"Name": "East"},
                        ],
                    }
                ]
            }
        )
        assert "tc-12345" in result
        assert "Region" in result
        assert "ACTIVE" in result
        assert "North" in result
        assert "South" in result

    def test_many_options_truncated(self) -> None:
        options = [{"Name": f"Opt{i}"} for i in range(8)]
        result = format_tracking_category_list(
            {
                "TrackingCategories": [
                    {"TrackingCategoryID": "tc-1", "Name": "Cat", "Status": "ACTIVE", "Options": options}
                ]
            }
        )
        assert "+3 more" in result

    def test_no_options(self) -> None:
        result = format_tracking_category_list(
            {"TrackingCategories": [{"TrackingCategoryID": "tc-1", "Name": "Cat", "Status": "ACTIVE", "Options": []}]}
        )
        assert "no options" in result


class TestFormatBrandingThemeList:
    def test_empty(self) -> None:
        assert format_branding_theme_list({"BrandingThemes": []}) == "No branding themes found."

    def test_single_theme(self) -> None:
        result = format_branding_theme_list(
            {
                "BrandingThemes": [
                    {"BrandingThemeID": "bt-12345678-abcd", "Name": "Standard", "SortOrder": 0},
                ]
            }
        )
        assert "bt-12345" in result
        assert "Standard" in result
        assert "sort=0" in result

    def test_no_sort_order(self) -> None:
        result = format_branding_theme_list(
            {
                "BrandingThemes": [
                    {"BrandingThemeID": "bt-1", "Name": "Custom"},
                ]
            }
        )
        assert "sort=" not in result


# ===========================================================================
# Manual Journal formatters
# ===========================================================================


class TestFormatManualJournalList:
    def test_empty(self) -> None:
        assert format_manual_journal_list({"ManualJournals": []}) == "No manual journals found."

    def test_single_journal(self) -> None:
        result = format_manual_journal_list(
            {
                "ManualJournals": [
                    {
                        "ManualJournalID": "mj-12345678-abcd",
                        "Narration": "Year-end adjustment entry",
                        "Status": "POSTED",
                        "DateString": "2026-03-31",
                    }
                ]
            }
        )
        assert "mj-12345" in result
        assert "Year-end adjustment" in result
        assert "POSTED" in result

    def test_long_narration_truncated(self) -> None:
        result = format_manual_journal_list(
            {
                "ManualJournals": [
                    {
                        "ManualJournalID": "mj-1",
                        "Narration": "A" * 80,
                        "Status": "DRAFT",
                        "DateString": "2026-03-31",
                    }
                ]
            }
        )
        # Narration is truncated to 40 chars
        lines = result.strip().split("\n")
        narration_part = lines[0].split(" | ")[1]
        assert len(narration_part) <= 40


# ===========================================================================
# Payroll AU — Employee formatters
# ===========================================================================


class TestFormatEmployeeList:
    def test_empty(self) -> None:
        assert format_employee_list({"Employees": []}) == "No employees found."

    def test_single_employee(self) -> None:
        result = format_employee_list({"Employees": [SAMPLE_EMPLOYEE]})
        assert "emp-1234" in result
        assert "Jane Smith" in result
        assert "ACTIVE" in result
        assert "jane.smith@example.com" in result

    def test_no_email(self) -> None:
        emp = {**SAMPLE_EMPLOYEE}
        del emp["Email"]
        result = format_employee_list({"Employees": [emp]})
        assert "@" not in result


class TestFormatEmployeeDetail:
    def test_full_detail(self) -> None:
        result = format_employee_detail({"Employees": [SAMPLE_EMPLOYEE]})
        assert "Jane Smith" in result
        assert "ACTIVE" in result
        assert "jane.smith@example.com" in result
        assert "Developer" in result
        assert "Full-Time" in result
        assert "456 Oak Ave" in result
        assert "Melbourne" in result

    def test_super_memberships(self) -> None:
        result = format_employee_detail({"Employees": [SAMPLE_EMPLOYEE]})
        assert "Super Funds (1)" in result
        assert "EMP001" in result

    def test_tax_declaration(self) -> None:
        result = format_employee_detail({"Employees": [SAMPLE_EMPLOYEE]})
        assert "Tax Free Threshold" in result


# ===========================================================================
# Payroll AU — Timesheet formatters
# ===========================================================================


class TestFormatTimesheetList:
    def test_empty(self) -> None:
        assert format_timesheet_list({"Timesheets": []}) == "No timesheets found."

    def test_single_timesheet(self) -> None:
        result = format_timesheet_list({"Timesheets": [SAMPLE_TIMESHEET]})
        assert "ts-12345" in result
        assert "emp-1234" in result
        assert "DRAFT" in result
        assert "40" in result


class TestFormatTimesheetDetail:
    def test_full_detail(self) -> None:
        result = format_timesheet_detail({"Timesheets": [SAMPLE_TIMESHEET]})
        assert "DRAFT" in result
        assert "40" in result
        assert "Lines (1)" in result
        assert "er-12345" in result


# ===========================================================================
# Payroll AU — Payslip formatters
# ===========================================================================


class TestFormatPayslipList:
    def test_empty(self) -> None:
        assert format_payslip_list({"PayRuns": [{"Payslips": []}]}) == "No payslips found."

    def test_single_payslip(self) -> None:
        result = format_payslip_list(
            {
                "PayRuns": [
                    {
                        "Payslips": [
                            {
                                "PayslipID": "ps-12345678",
                                "EmployeeID": "emp-12345678",
                                "FirstName": "Jane",
                                "LastName": "Smith",
                                "NetPay": 3500.00,
                            }
                        ]
                    }
                ]
            }
        )
        assert "ps-12345" in result
        assert "Jane Smith" in result
        assert "net=" in result
        assert "3,500.00" in result

    def test_payrun_as_dict(self) -> None:
        result = format_payslip_list(
            {
                "PayRuns": {
                    "Payslips": [
                        {"PayslipID": "ps-1", "EmployeeID": "emp-1", "FirstName": "A", "LastName": "B", "NetPay": 100}
                    ]
                }
            }
        )
        assert "ps-1" in result

    def test_empty_payrun_list(self) -> None:
        result = format_payslip_list({"PayRuns": []})
        assert "No payslips found." == result


class TestFormatPayslipDetail:
    def test_full_detail(self) -> None:
        result = format_payslip_detail({"Payslip": SAMPLE_PAYSLIP})
        assert "Jane Smith" in result
        assert "3,500.00" in result
        assert "850.00" in result
        assert "420.00" in result
        assert "Earnings (1)" in result
        assert "Deductions (1)" in result
        assert "Super (1)" in result

    def test_minimal_payslip(self) -> None:
        result = format_payslip_detail({"Payslip": {"PayslipID": "ps-1", "FirstName": "A", "LastName": "B"}})
        assert "A B" in result


# ===========================================================================
# Webhook verification formatter
# ===========================================================================


class TestFormatWebhookVerification:
    def test_valid(self) -> None:
        result = format_webhook_verification({"valid": True, "event_count": 3})
        assert "Valid webhook" in result
        assert "3" in result

    def test_invalid(self) -> None:
        result = format_webhook_verification({"valid": False, "error": "Signature mismatch"})
        assert "Invalid webhook" in result
        assert "Signature mismatch" in result

    def test_invalid_no_error(self) -> None:
        result = format_webhook_verification({"valid": False})
        assert "verification failed" in result


# ===========================================================================
# Helper: _add
# ===========================================================================


class TestAddHelper:
    def test_none_value_omitted(self) -> None:
        """None values should not generate lines in detail formatters."""
        contact = {
            "ContactID": "c-1",
            "Name": "Test",
            "ContactStatus": None,
            "EmailAddress": None,
        }
        result = format_contact_detail(contact)
        assert "Status:" not in result
        assert "Email:" not in result

    def test_empty_string_omitted(self) -> None:
        contact = {
            "ContactID": "c-1",
            "Name": "Test",
            "ContactStatus": "",
        }
        result = format_contact_detail(contact)
        assert "Status:" not in result


# ===========================================================================
# Helper: _format_phone
# ===========================================================================


class TestPhoneFormatting:
    def test_full_phone(self) -> None:
        contact = {
            **SAMPLE_CONTACT,
            "Phones": [
                {"PhoneType": "DEFAULT", "PhoneNumber": "5551234", "PhoneAreaCode": "02", "PhoneCountryCode": "61"}
            ],
        }
        result = format_contact_detail({"Contacts": [contact]})
        assert "+61" in result
        assert "(02)" in result
        assert "5551234" in result

    def test_phone_without_country(self) -> None:
        contact = {
            **SAMPLE_CONTACT,
            "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": "5551234", "PhoneAreaCode": "02"}],
        }
        result = format_contact_detail({"Contacts": [contact]})
        assert "(02)" in result
        assert "5551234" in result
        assert "+61" not in result

    def test_phone_without_area(self) -> None:
        contact = {
            **SAMPLE_CONTACT,
            "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": "5551234"}],
        }
        result = format_contact_detail({"Contacts": [contact]})
        assert "5551234" in result

    def test_empty_phones_list(self) -> None:
        contact = {**SAMPLE_CONTACT, "Phones": []}
        result = format_contact_detail({"Contacts": [contact]})
        assert "Phone:" not in result

    def test_phone_no_number(self) -> None:
        contact = {**SAMPLE_CONTACT, "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": ""}]}
        result = format_contact_detail({"Contacts": [contact]})
        assert "Phone:" not in result
