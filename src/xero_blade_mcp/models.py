"""Shared constants, types, and gates for Xero Blade MCP server."""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE = 100  # Xero default and max per page
MAX_PAGE_SIZE = 100  # Xero API max (some endpoints support up to 1000)
MAX_BODY_CHARS = 50_000

# ---------------------------------------------------------------------------
# Base URLs
# ---------------------------------------------------------------------------

ACCOUNTING_API_URL = "https://api.xero.com/api.xro/2.0"
PAYROLL_AU_API_URL = "https://api.xero.com/payroll.xro/1.0"
IDENTITY_API_URL = "https://api.xero.com/connections"
TOKEN_URL = "https://identity.xero.com/connect/token"
AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"

# ---------------------------------------------------------------------------
# Invoice types (Xero overloads the Invoices endpoint)
# ---------------------------------------------------------------------------

INVOICE_TYPE_SALES = "ACCREC"  # Accounts Receivable = Sales Invoice
INVOICE_TYPE_BILL = "ACCPAY"  # Accounts Payable = Purchase Bill

# ---------------------------------------------------------------------------
# Invoice statuses
# ---------------------------------------------------------------------------

INVOICE_STATUSES = {"DRAFT", "SUBMITTED", "AUTHORISED", "PAID", "VOIDED", "DELETED"}
CONTACT_STATUSES = {"ACTIVE", "ARCHIVED", "GDPRREQUEST"}

# ---------------------------------------------------------------------------
# Currency symbols for human-readable money formatting
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AUD": "A$",
    "NZD": "NZ$",
    "CAD": "C$",
    "HKD": "HK$",
    "SGD": "S$",
    "JPY": "¥",
    "CNY": "¥",
    "CHF": "CHF ",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "INR": "₹",
    "BRL": "R$",
    "KRW": "₩",
    "MXN": "MX$",
    "PLN": "zł",
    "THB": "฿",
    "TRY": "₺",
    "ZAR": "R",
}

ZERO_DECIMAL_CURRENCIES: set[str] = {"JPY", "KRW", "VND"}


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------


def is_write_enabled() -> bool:
    """Check if write operations are enabled via env var."""
    return os.environ.get("XERO_WRITE_ENABLED", "").lower() == "true"


def require_write() -> str | None:
    """Return an error message if writes are disabled, else None."""
    if not is_write_enabled():
        return "Error: Write operations are disabled. Set XERO_WRITE_ENABLED=true to enable."
    return None


# ---------------------------------------------------------------------------
# Confirm gate (for destructive operations)
# ---------------------------------------------------------------------------


def require_confirm(confirm: bool, action: str) -> str | None:
    """Return an error message if confirm is False for a destructive operation."""
    if not confirm:
        return f"Error: {action} requires confirm=true. This action may be difficult to reverse."
    return None


# ---------------------------------------------------------------------------
# Money formatting
# ---------------------------------------------------------------------------


def format_money(amount: str | float | int | None, currency_code: str) -> str:
    """Format a Xero money amount for human-readable output.

    Xero stores amounts as decimal strings or floats (e.g., 29.00).

    Examples:
        format_money("150.00", "AUD") -> "A$150.00 AUD"
        format_money(1000, "JPY") -> "¥1000 JPY"
        format_money(None, "AUD") -> "? AUD"
    """
    if amount is None:
        return f"? {currency_code}"

    try:
        value = float(amount)
    except (ValueError, TypeError):
        return f"{amount} {currency_code}"

    symbol = CURRENCY_SYMBOLS.get(currency_code, "")

    if currency_code in ZERO_DECIMAL_CURRENCIES:
        return f"{symbol}{int(value)} {currency_code}"

    return f"{symbol}{value:,.2f} {currency_code}"


# ---------------------------------------------------------------------------
# Token scrubbing
# ---------------------------------------------------------------------------

_SCRUB_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Bearer\s+[^\s]+", re.IGNORECASE),
    re.compile(r"[A-Fa-f0-9]{32,}"),  # Long hex strings (tokens, secrets)
    re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWTs
]


def scrub_secrets(text: str) -> str:
    """Remove API keys, tokens, and JWTs from text to prevent leakage."""
    result = text
    for pattern in _SCRUB_PATTERNS:
        result = pattern.sub("****", result)
    return result
