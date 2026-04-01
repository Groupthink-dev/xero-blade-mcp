"""Token-efficient output formatters for Xero data.

Design principles:
- Concise by default (one line per item)
- Null fields omitted
- Pipe-delimited lists
- Money in human-readable format (A$150.00 AUD)
- Dates in short format (2026-03-15)
- Page hints for pagination
"""

from __future__ import annotations

from typing import Any

from xero_blade_mcp.models import format_money

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def format_xero_date(date_str: str | None) -> str:
    """Format Xero date string to short form.

    Xero uses '/Date(timestamp)/' or ISO formats.
    """
    if not date_str:
        return "?"
    # Handle Xero's .NET JSON date format: /Date(1234567890000+0000)/
    if date_str.startswith("/Date("):
        import datetime

        ms_str = date_str.split("(")[1].split("+")[0].split("-")[0].split(")")[0]
        try:
            ts = int(ms_str) / 1000
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.UTC)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return date_str
    # Handle ISO format
    return date_str[:10]


def format_datetime_short(date_str: str | None) -> str:
    """Format to short datetime: '2026-03-15T14:30:00' -> '2026-03-15 14:30'."""
    if not date_str:
        return "?"
    if date_str.startswith("/Date("):
        return format_xero_date(date_str)
    clean = date_str.replace("Z", "").replace("+00:00", "")
    return clean[:16].replace("T", " ")


# ---------------------------------------------------------------------------
# Field selection
# ---------------------------------------------------------------------------


def select_fields(data: dict[str, Any], fields: str | None) -> dict[str, Any]:
    """Filter dict to only requested fields, always including ID fields."""
    if not fields:
        return data
    wanted = {f.strip() for f in fields.split(",")}
    for id_key in ("ContactID", "InvoiceID", "BankTransactionID", "PaymentID", "CreditNoteID"):
        if id_key in data:
            wanted.add(id_key)
    return {k: v for k, v in data.items() if k in wanted}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def format_page_hint(items_count: int, page: int, page_size: int = 100) -> str:
    """Generate pagination hint for Xero's offset-based pagination."""
    if items_count >= page_size:
        return f"… more results (pass page={page + 1} to continue)"
    return ""


# ---------------------------------------------------------------------------
# Connection / Organisation formatters
# ---------------------------------------------------------------------------


def format_connection_list(connections: list[dict[str, Any]]) -> str:
    """Format tenant connection list."""
    if not connections:
        return "No connected organisations."

    lines: list[str] = []
    for c in connections:
        parts = [
            c.get("tenantId", "?"),
            c.get("tenantName", "(unnamed)"),
            c.get("tenantType", "?"),
        ]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_organisation_detail(response: dict[str, Any]) -> str:
    """Format organisation detail."""
    orgs = response.get("Organisations", [])
    if not orgs:
        return "No organisation data."

    org = orgs[0]
    lines: list[str] = []
    _add(lines, "Name", org.get("Name"))
    _add(lines, "Legal Name", org.get("LegalName"))
    _add(lines, "Short Code", org.get("ShortCode"))
    _add(lines, "Country", org.get("CountryCode"))
    _add(lines, "Base Currency", org.get("BaseCurrency"))
    _add(lines, "Org Type", org.get("OrganisationType"))
    _add(lines, "Class", org.get("Class"))
    _add(lines, "Version", org.get("Version"))
    _add(lines, "Tax Number", org.get("TaxNumber"))
    fy_day = org.get("FinancialYearEndDay", "")
    fy_month = org.get("FinancialYearEndMonth", "")
    _add(lines, "Financial Year End", f"{fy_day}/{fy_month}")
    _add(lines, "Sales Tax Basis", org.get("SalesTaxBasis"))
    _add(lines, "Sales Tax Period", org.get("SalesTaxPeriod"))
    _add(lines, "Timezone", org.get("Timezone"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Contact formatters
# ---------------------------------------------------------------------------


def format_contact_list(response: dict[str, Any], page: int = 1) -> str:
    """Format contact list — one line per contact."""
    contacts = response.get("Contacts", [])
    if not contacts:
        return "No contacts found."

    lines: list[str] = []
    for c in contacts:
        parts = [
            c.get("ContactID", "?")[:8],
            c.get("Name", "(unnamed)"),
            c.get("ContactStatus", "?"),
        ]
        email = c.get("EmailAddress")
        if email:
            parts.append(email)
        is_customer = c.get("IsCustomer", False)
        is_supplier = c.get("IsSupplier", False)
        roles = []
        if is_customer:
            roles.append("customer")
        if is_supplier:
            roles.append("supplier")
        if roles:
            parts.append("+".join(roles))
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(contacts), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def format_contact_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format contact detail."""
    contacts = data.get("Contacts", [data]) if "Contacts" in data else [data]
    c = contacts[0] if contacts else data
    c = select_fields(c, fields)

    lines: list[str] = []
    _add(lines, "ID", c.get("ContactID"))
    _add(lines, "Name", c.get("Name"))
    _add(lines, "Status", c.get("ContactStatus"))
    _add(lines, "Email", c.get("EmailAddress"))
    _add(lines, "First Name", c.get("FirstName"))
    _add(lines, "Last Name", c.get("LastName"))
    _add(lines, "Phone", _format_phone(c.get("Phones", [])))
    _add(lines, "Tax Number", c.get("TaxNumber"))
    _add(lines, "Account Number", c.get("AccountNumber"))
    _add(lines, "Customer", str(c.get("IsCustomer", False)))
    _add(lines, "Supplier", str(c.get("IsSupplier", False)))
    _add(lines, "Default Currency", c.get("DefaultCurrency"))

    addresses = c.get("Addresses", [])
    for addr in addresses:
        addr_type = addr.get("AddressType", "?")
        addr_fields = [
            addr.get("AddressLine1"),
            addr.get("City"),
            addr.get("Region"),
            addr.get("PostalCode"),
            addr.get("Country"),
        ]
        parts = [p for p in addr_fields if p]
        if parts:
            lines.append(f"Address ({addr_type}): {', '.join(parts)}")

    balances = c.get("Balances", {})
    if balances:
        ar = balances.get("AccountsReceivable", {})
        ap = balances.get("AccountsPayable", {})
        if ar.get("Outstanding"):
            lines.append(f"AR Outstanding: {ar['Outstanding']}")
        if ap.get("Outstanding"):
            lines.append(f"AP Outstanding: {ap['Outstanding']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Invoice formatters
# ---------------------------------------------------------------------------


def format_invoice_list(response: dict[str, Any], page: int = 1, label: str = "invoices") -> str:
    """Format invoice/bill list — one line per item."""
    invoices = response.get("Invoices", [])
    if not invoices:
        return f"No {label} found."

    lines: list[str] = []
    for inv in invoices:
        currency = inv.get("CurrencyCode", "AUD")
        parts = [
            inv.get("InvoiceNumber") or inv.get("InvoiceID", "?")[:8],
            inv.get("Contact", {}).get("Name", "?"),
            inv.get("Status", "?"),
            format_money(inv.get("Total"), currency),
            format_xero_date(inv.get("DueDateString") or inv.get("DueDate")),
        ]
        amount_due = inv.get("AmountDue")
        if amount_due and float(amount_due) > 0 and inv.get("Status") not in ("PAID", "VOIDED"):
            parts.append(f"due={format_money(amount_due, currency)}")
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(invoices), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def format_invoice_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format invoice/bill detail."""
    invoices = data.get("Invoices", [data]) if "Invoices" in data else [data]
    inv = invoices[0] if invoices else data
    inv = select_fields(inv, fields)
    currency = inv.get("CurrencyCode", "AUD")

    lines: list[str] = []
    _add(lines, "ID", inv.get("InvoiceID"))
    _add(lines, "Number", inv.get("InvoiceNumber"))
    _add(lines, "Type", "Sales Invoice" if inv.get("Type") == "ACCREC" else "Bill")
    _add(lines, "Status", inv.get("Status"))
    _add(lines, "Reference", inv.get("Reference"))
    _add(lines, "Contact", inv.get("Contact", {}).get("Name"))
    _add(lines, "Date", format_xero_date(inv.get("DateString") or inv.get("Date")))
    _add(lines, "Due Date", format_xero_date(inv.get("DueDateString") or inv.get("DueDate")))

    # Line items
    line_items = inv.get("LineItems", [])
    if line_items:
        lines.append(f"Line Items ({len(line_items)}):")
        for li in line_items[:10]:
            desc = li.get("Description", "(no description)")[:50]
            qty = li.get("Quantity", "?")
            unit_amt = li.get("UnitAmount", "?")
            line_total = format_money(li.get("LineAmount"), currency)
            lines.append(f"  {desc} | qty={qty} | unit={unit_amt} | {line_total}")
        if len(line_items) > 10:
            lines.append(f"  … +{len(line_items) - 10} more")

    _add(lines, "Subtotal", format_money(inv.get("SubTotal"), currency))
    tax = inv.get("TotalTax")
    if tax and float(tax) != 0:
        _add(lines, "Tax", format_money(tax, currency))
    _add(lines, "Total", format_money(inv.get("Total"), currency))
    amount_due = inv.get("AmountDue")
    if amount_due and float(amount_due) > 0:
        _add(lines, "Amount Due", format_money(amount_due, currency))
    _add(lines, "Amount Paid", format_money(inv.get("AmountPaid"), currency))

    # Payments
    payments = inv.get("Payments", [])
    if payments:
        lines.append(f"Payments ({len(payments)}):")
        for p in payments[:5]:
            p_amount = format_money(p.get("Amount"), currency)
            p_date = format_xero_date(p.get("Date"))
            lines.append(f"  {p.get('PaymentID', '?')[:8]} | {p_amount} | {p_date}")

    _add(lines, "Updated", format_datetime_short(inv.get("UpdatedDateUTC")))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bank Transaction formatters
# ---------------------------------------------------------------------------


def format_bank_transaction_list(response: dict[str, Any], page: int = 1) -> str:
    """Format bank transaction list."""
    txns = response.get("BankTransactions", [])
    if not txns:
        return "No bank transactions found."

    lines: list[str] = []
    for t in txns:
        currency = t.get("CurrencyCode", "AUD")
        parts = [
            t.get("BankTransactionID", "?")[:8],
            t.get("Type", "?"),
            t.get("Contact", {}).get("Name", "?"),
            format_money(t.get("Total"), currency),
            t.get("Status", "?"),
            format_xero_date(t.get("DateString") or t.get("Date")),
        ]
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(txns), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def format_bank_transaction_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format bank transaction detail."""
    txns = data.get("BankTransactions", [data]) if "BankTransactions" in data else [data]
    t = txns[0] if txns else data
    t = select_fields(t, fields)
    currency = t.get("CurrencyCode", "AUD")

    lines: list[str] = []
    _add(lines, "ID", t.get("BankTransactionID"))
    _add(lines, "Type", t.get("Type"))
    _add(lines, "Status", t.get("Status"))
    _add(lines, "Contact", t.get("Contact", {}).get("Name"))
    _add(lines, "Date", format_xero_date(t.get("DateString") or t.get("Date")))
    _add(lines, "Reference", t.get("Reference"))
    _add(lines, "Bank Account", t.get("BankAccount", {}).get("Name"))

    line_items = t.get("LineItems", [])
    if line_items:
        lines.append(f"Line Items ({len(line_items)}):")
        for li in line_items[:5]:
            desc = li.get("Description", "?")[:50]
            amount = format_money(li.get("LineAmount"), currency)
            lines.append(f"  {desc} | {amount}")

    _add(lines, "Subtotal", format_money(t.get("SubTotal"), currency))
    _add(lines, "Total", format_money(t.get("Total"), currency))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Payment formatters
# ---------------------------------------------------------------------------


def format_payment_list(response: dict[str, Any], page: int = 1) -> str:
    """Format payment list."""
    payments = response.get("Payments", [])
    if not payments:
        return "No payments found."

    lines: list[str] = []
    for p in payments:
        currency = p.get("CurrencyCode", "AUD")
        parts = [
            p.get("PaymentID", "?")[:8],
            format_money(p.get("Amount"), currency),
            p.get("Status", "?"),
            format_xero_date(p.get("Date")),
        ]
        inv = p.get("Invoice", {})
        if inv.get("InvoiceNumber"):
            parts.append(f"inv={inv['InvoiceNumber']}")
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(payments), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def format_payment_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format payment detail."""
    payments = data.get("Payments", [data]) if "Payments" in data else [data]
    p = payments[0] if payments else data
    p = select_fields(p, fields)
    currency = p.get("CurrencyCode", "AUD")

    lines: list[str] = []
    _add(lines, "ID", p.get("PaymentID"))
    _add(lines, "Amount", format_money(p.get("Amount"), currency))
    _add(lines, "Status", p.get("Status"))
    _add(lines, "Date", format_xero_date(p.get("Date")))
    _add(lines, "Payment Type", p.get("PaymentType"))
    _add(lines, "Reference", p.get("Reference"))
    inv = p.get("Invoice", {})
    _add(lines, "Invoice", inv.get("InvoiceNumber") or inv.get("InvoiceID"))
    _add(lines, "Account", p.get("Account", {}).get("Name"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Credit Note formatters
# ---------------------------------------------------------------------------


def format_credit_note_list(response: dict[str, Any], page: int = 1) -> str:
    """Format credit note list."""
    notes = response.get("CreditNotes", [])
    if not notes:
        return "No credit notes found."

    lines: list[str] = []
    for cn in notes:
        currency = cn.get("CurrencyCode", "AUD")
        parts = [
            cn.get("CreditNoteNumber") or cn.get("CreditNoteID", "?")[:8],
            cn.get("Contact", {}).get("Name", "?"),
            cn.get("Status", "?"),
            format_money(cn.get("Total"), currency),
            format_xero_date(cn.get("DateString") or cn.get("Date")),
        ]
        remaining = cn.get("RemainingCredit")
        if remaining and float(remaining) > 0:
            parts.append(f"remaining={format_money(remaining, currency)}")
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(notes), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Purchase Order formatters
# ---------------------------------------------------------------------------


def format_purchase_order_list(response: dict[str, Any], page: int = 1) -> str:
    """Format purchase order list."""
    orders = response.get("PurchaseOrders", [])
    if not orders:
        return "No purchase orders found."

    lines: list[str] = []
    for po in orders:
        currency = po.get("CurrencyCode", "AUD")
        parts = [
            po.get("PurchaseOrderNumber") or po.get("PurchaseOrderID", "?")[:8],
            po.get("Contact", {}).get("Name", "?"),
            po.get("Status", "?"),
            format_money(po.get("Total"), currency),
            format_xero_date(po.get("DateString") or po.get("Date")),
        ]
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(orders), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quote formatters
# ---------------------------------------------------------------------------


def format_quote_list(response: dict[str, Any], page: int = 1) -> str:
    """Format quote list."""
    quotes = response.get("Quotes", [])
    if not quotes:
        return "No quotes found."

    lines: list[str] = []
    for q in quotes:
        currency = q.get("CurrencyCode", "AUD")
        parts = [
            q.get("QuoteNumber") or q.get("QuoteID", "?")[:8],
            q.get("Contact", {}).get("Name", "?"),
            q.get("Status", "?"),
            format_money(q.get("Total"), currency),
            format_xero_date(q.get("DateString") or q.get("Date")),
        ]
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(quotes), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Account / Chart of Accounts formatters
# ---------------------------------------------------------------------------


def format_account_list(response: dict[str, Any]) -> str:
    """Format chart of accounts list."""
    accounts = response.get("Accounts", [])
    if not accounts:
        return "No accounts found."

    lines: list[str] = []
    for a in accounts:
        parts = [
            a.get("Code", "?"),
            a.get("Name", "(unnamed)"),
            a.get("Type", "?"),
            a.get("Class", "?"),
            a.get("Status", "?"),
        ]
        if a.get("TaxType"):
            parts.append(f"tax={a['TaxType']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_account_detail(data: dict[str, Any], fields: str | None = None) -> str:
    """Format account detail."""
    accounts = data.get("Accounts", [data]) if "Accounts" in data else [data]
    a = accounts[0] if accounts else data
    a = select_fields(a, fields)

    lines: list[str] = []
    _add(lines, "ID", a.get("AccountID"))
    _add(lines, "Code", a.get("Code"))
    _add(lines, "Name", a.get("Name"))
    _add(lines, "Type", a.get("Type"))
    _add(lines, "Class", a.get("Class"))
    _add(lines, "Status", a.get("Status"))
    _add(lines, "Tax Type", a.get("TaxType"))
    _add(lines, "Description", a.get("Description"))
    _add(lines, "Bank Account Type", a.get("BankAccountType"))
    _add(lines, "Currency", a.get("CurrencyCode"))
    _add(lines, "Enable Payments", str(a.get("EnablePaymentsToAccount", "")))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report formatters
# ---------------------------------------------------------------------------


def format_report(response: dict[str, Any]) -> str:
    """Format a Xero standard report (P&L, Balance Sheet, Trial Balance, etc.)."""
    reports = response.get("Reports", [])
    if not reports:
        return "No report data."

    report = reports[0]
    lines: list[str] = []
    lines.append(f"Report: {report.get('ReportName', '?')}")
    lines.append(f"Date: {report.get('ReportDate', '?')}")

    for row_group in report.get("Rows", []):
        row_type = row_group.get("RowType", "")
        title = row_group.get("Title", "")

        if row_type == "Header":
            cells = row_group.get("Cells", [])
            header_parts = [c.get("Value", "") for c in cells]
            lines.append("\n" + " | ".join(header_parts))
            lines.append("-" * 60)
        elif row_type == "Section":
            if title:
                lines.append(f"\n{title}")
            for row in row_group.get("Rows", []):
                cells = row.get("Cells", [])
                parts = [c.get("Value", "") for c in cells]
                if any(parts):
                    lines.append("  " + " | ".join(parts))
        elif row_type == "SummaryRow":
            cells = row_group.get("Cells", [])
            parts = [c.get("Value", "") for c in cells]
            if any(parts):
                lines.append("  **" + " | ".join(parts) + "**")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tax / Currency / Tracking formatters
# ---------------------------------------------------------------------------


def format_tax_rate_list(response: dict[str, Any]) -> str:
    """Format tax rate list."""
    rates = response.get("TaxRates", [])
    if not rates:
        return "No tax rates found."

    lines: list[str] = []
    for r in rates:
        parts = [
            r.get("TaxType", "?"),
            r.get("Name", "(unnamed)"),
            f"{r.get('EffectiveRate', '?')}%",
            r.get("Status", "?"),
        ]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_currency_list(response: dict[str, Any]) -> str:
    """Format currency list."""
    currencies = response.get("Currencies", [])
    if not currencies:
        return "No currencies found."

    lines: list[str] = []
    for c in currencies:
        parts = [c.get("Code", "?"), c.get("Description", "(unnamed)")]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_tracking_category_list(response: dict[str, Any]) -> str:
    """Format tracking category list."""
    categories = response.get("TrackingCategories", [])
    if not categories:
        return "No tracking categories found."

    lines: list[str] = []
    for cat in categories:
        options = cat.get("Options", [])
        option_names = ", ".join(o.get("Name", "?") for o in options[:5])
        if len(options) > 5:
            option_names += f", +{len(options) - 5} more"
        parts = [
            cat.get("TrackingCategoryID", "?")[:8],
            cat.get("Name", "(unnamed)"),
            cat.get("Status", "?"),
            f"options: {option_names}" if option_names else "no options",
        ]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_branding_theme_list(response: dict[str, Any]) -> str:
    """Format branding theme list."""
    themes = response.get("BrandingThemes", [])
    if not themes:
        return "No branding themes found."

    lines: list[str] = []
    for t in themes:
        parts = [
            t.get("BrandingThemeID", "?")[:8],
            t.get("Name", "(unnamed)"),
        ]
        if t.get("SortOrder") is not None:
            parts.append(f"sort={t['SortOrder']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Manual Journal formatters
# ---------------------------------------------------------------------------


def format_manual_journal_list(response: dict[str, Any], page: int = 1) -> str:
    """Format manual journal list."""
    journals = response.get("ManualJournals", [])
    if not journals:
        return "No manual journals found."

    lines: list[str] = []
    for j in journals:
        parts = [
            j.get("ManualJournalID", "?")[:8],
            j.get("Narration", "(no narration)")[:40],
            j.get("Status", "?"),
            format_xero_date(j.get("DateString") or j.get("Date")),
        ]
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(journals), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Payroll AU formatters
# ---------------------------------------------------------------------------


def format_employee_list(response: dict[str, Any], page: int = 1) -> str:
    """Format payroll employee list."""
    employees = response.get("Employees", [])
    if not employees:
        return "No employees found."

    lines: list[str] = []
    for e in employees:
        parts = [
            e.get("EmployeeID", "?")[:8],
            f"{e.get('FirstName', '?')} {e.get('LastName', '')}".strip(),
            e.get("Status", "?"),
        ]
        email = e.get("Email")
        if email:
            parts.append(email)
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(employees), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def format_employee_detail(data: dict[str, Any]) -> str:
    """Format payroll employee detail."""
    employees = data.get("Employees", [data]) if "Employees" in data else [data]
    e = employees[0] if employees else data

    lines: list[str] = []
    _add(lines, "ID", e.get("EmployeeID"))
    _add(lines, "Name", f"{e.get('FirstName', '?')} {e.get('LastName', '')}".strip())
    _add(lines, "Status", e.get("Status"))
    _add(lines, "Email", e.get("Email"))
    _add(lines, "Date of Birth", format_xero_date(e.get("DateOfBirth")))
    _add(lines, "Start Date", format_xero_date(e.get("StartDate")))
    _add(lines, "Termination Date", format_xero_date(e.get("TerminationDate")))
    _add(lines, "Job Title", e.get("JobTitle"))
    _add(lines, "Classification", e.get("Classification"))
    _add(lines, "Ordinary Earnings Rate", e.get("OrdinaryEarningsRateID"))

    home = e.get("HomeAddress", {})
    if home:
        home_fields = [home.get("AddressLine1"), home.get("City"), home.get("Region"), home.get("PostalCode")]
        addr_parts = [p for p in home_fields if p]
        if addr_parts:
            lines.append(f"Address: {', '.join(addr_parts)}")

    tax = e.get("TaxDeclaration", {})
    if tax:
        _add(lines, "TFN Status", tax.get("TFNPendingOrExemptionHeld"))
        _add(lines, "Tax Free Threshold", str(tax.get("TaxFreeThresholdClaimed", "")))

    super_lines = e.get("SuperMemberships", [])
    if super_lines:
        lines.append(f"Super Funds ({len(super_lines)}):")
        for s in super_lines[:3]:
            lines.append(f"  {s.get('SuperFundID', '?')[:8]} | member={s.get('EmployeeNumber', '?')}")

    return "\n".join(lines)


def format_timesheet_list(response: dict[str, Any], page: int = 1) -> str:
    """Format payroll timesheet list."""
    timesheets = response.get("Timesheets", [])
    if not timesheets:
        return "No timesheets found."

    lines: list[str] = []
    for ts in timesheets:
        parts = [
            ts.get("TimesheetID", "?")[:8],
            ts.get("EmployeeID", "?")[:8],
            ts.get("Status", "?"),
            f"{format_xero_date(ts.get('StartDate'))} to {format_xero_date(ts.get('EndDate'))}",
        ]
        hours = ts.get("Hours")
        if hours is not None:
            parts.append(f"{hours}h")
        lines.append(" | ".join(parts))

    hint = format_page_hint(len(timesheets), page)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def format_timesheet_detail(data: dict[str, Any]) -> str:
    """Format payroll timesheet detail."""
    timesheets = data.get("Timesheets", [data]) if "Timesheets" in data else [data]
    ts = timesheets[0] if timesheets else data

    lines: list[str] = []
    _add(lines, "ID", ts.get("TimesheetID"))
    _add(lines, "Employee", ts.get("EmployeeID"))
    _add(lines, "Status", ts.get("Status"))
    _add(lines, "Period", f"{format_xero_date(ts.get('StartDate'))} to {format_xero_date(ts.get('EndDate'))}")
    _add(lines, "Hours", str(ts.get("Hours", "")))

    timesheet_lines = ts.get("TimesheetLines", [])
    if timesheet_lines:
        lines.append(f"Lines ({len(timesheet_lines)}):")
        for tl in timesheet_lines[:10]:
            earnings_rate = tl.get("EarningsRateID", "?")[:8]
            units = tl.get("NumberOfUnits", [])
            total = sum(float(u) for u in units if u) if units else 0
            lines.append(f"  {earnings_rate} | {total}h | units={units}")

    return "\n".join(lines)


def format_payslip_list(response: dict[str, Any]) -> str:
    """Format payslip list from a pay run."""
    payrun = response.get("PayRuns", [{}])
    if isinstance(payrun, list):
        payrun = payrun[0] if payrun else {}
    payslips = payrun.get("Payslips", [])
    if not payslips:
        return "No payslips found."

    lines: list[str] = []
    for ps in payslips:
        parts = [
            ps.get("PayslipID", "?")[:8],
            ps.get("EmployeeID", "?")[:8],
            f"{ps.get('FirstName', '?')} {ps.get('LastName', '')}".strip(),
        ]
        net_pay = ps.get("NetPay")
        if net_pay is not None:
            parts.append(f"net={format_money(net_pay, 'AUD')}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_payslip_detail(data: dict[str, Any]) -> str:
    """Format individual payslip detail."""
    payslip = data.get("Payslip", data)

    lines: list[str] = []
    _add(lines, "ID", payslip.get("PayslipID"))
    _add(lines, "Employee", payslip.get("EmployeeID"))
    _add(lines, "Name", f"{payslip.get('FirstName', '?')} {payslip.get('LastName', '')}".strip())
    _add(lines, "Net Pay", format_money(payslip.get("NetPay"), "AUD"))
    _add(lines, "Tax", format_money(payslip.get("Tax"), "AUD"))
    _add(lines, "Super", format_money(payslip.get("Super"), "AUD"))

    earnings = payslip.get("EarningsLines", [])
    if earnings:
        lines.append(f"Earnings ({len(earnings)}):")
        for el in earnings[:5]:
            rate_id = el.get("EarningsRateID", "?")[:8]
            units = el.get("NumberOfUnits", "?")
            amt = format_money(el.get("Amount"), "AUD")
            lines.append(f"  {rate_id} | {units}h | {amt}")

    deductions = payslip.get("DeductionLines", [])
    if deductions:
        lines.append(f"Deductions ({len(deductions)}):")
        for dl in deductions[:5]:
            lines.append(f"  {dl.get('DeductionTypeID', '?')[:8]} | {format_money(dl.get('Amount'), 'AUD')}")

    super_lines = payslip.get("SuperannuationLines", [])
    if super_lines:
        lines.append(f"Super ({len(super_lines)}):")
        for sl in super_lines[:5]:
            lines.append(f"  {sl.get('SuperMembershipID', '?')[:8]} | {format_money(sl.get('Amount'), 'AUD')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Webhook verification formatter
# ---------------------------------------------------------------------------


def format_webhook_verification(result: dict[str, Any]) -> str:
    """Format webhook verification result."""
    if result.get("valid"):
        return f"Valid webhook | events: {result.get('event_count', '?')}"
    return f"Invalid webhook: {result.get('error', 'verification failed')}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add(lines: list[str], label: str, value: Any) -> None:
    """Append 'label: value' to lines if value is non-empty."""
    if value is not None and value != "" and value != "None":
        lines.append(f"{label}: {value}")


def _format_phone(phones: list[dict[str, Any]]) -> str | None:
    """Extract the first non-empty phone number."""
    for p in phones:
        number = p.get("PhoneNumber")
        if number:
            area = p.get("PhoneAreaCode", "")
            country = p.get("PhoneCountryCode", "")
            prefix = f"+{country} " if country else ""
            area_str = f"({area}) " if area else ""
            return f"{prefix}{area_str}{number}"
    return None
