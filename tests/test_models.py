"""Tests for xero_blade_mcp.models — gates, money formatting, token scrubbing."""

from __future__ import annotations

import pytest

from xero_blade_mcp.models import (
    CURRENCY_SYMBOLS,
    ZERO_DECIMAL_CURRENCIES,
    format_money,
    is_write_enabled,
    require_confirm,
    require_write,
    scrub_secrets,
)

# ===========================================================================
# Write gate
# ===========================================================================


class TestIsWriteEnabled:
    def test_disabled_by_default(self) -> None:
        assert is_write_enabled() is False

    def test_enabled_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "true")
        assert is_write_enabled() is True

    def test_enabled_true_uppercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "TRUE")
        assert is_write_enabled() is True

    def test_enabled_true_mixed_case(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "True")
        assert is_write_enabled() is True

    def test_disabled_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "false")
        assert is_write_enabled() is False

    def test_disabled_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "")
        assert is_write_enabled() is False

    def test_disabled_arbitrary_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "yes")
        assert is_write_enabled() is False

    def test_disabled_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "1")
        assert is_write_enabled() is False


class TestRequireWrite:
    def test_returns_error_when_disabled(self) -> None:
        result = require_write()
        assert result is not None
        assert "Write operations are disabled" in result
        assert "XERO_WRITE_ENABLED=true" in result

    def test_returns_none_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_WRITE_ENABLED", "true")
        assert require_write() is None


# ===========================================================================
# Confirm gate
# ===========================================================================


class TestRequireConfirm:
    def test_returns_error_when_false(self) -> None:
        result = require_confirm(False, "Void invoice")
        assert result is not None
        assert "Void invoice" in result
        assert "confirm=true" in result
        assert "difficult to reverse" in result

    def test_returns_none_when_true(self) -> None:
        assert require_confirm(True, "Void invoice") is None

    def test_includes_action_in_message(self) -> None:
        result = require_confirm(False, "Delete payment")
        assert result is not None
        assert "Delete payment" in result

    def test_includes_action_archive(self) -> None:
        result = require_confirm(False, "Archive contact")
        assert result is not None
        assert "Archive contact" in result


# ===========================================================================
# Money formatting
# ===========================================================================


class TestFormatMoney:
    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [
            ("150.00", "AUD", "A$150.00 AUD"),
            ("1000.50", "AUD", "A$1,000.50 AUD"),
            (29.00, "AUD", "A$29.00 AUD"),
            (0, "AUD", "A$0.00 AUD"),
            ("1234567.89", "AUD", "A$1,234,567.89 AUD"),
        ],
    )
    def test_aud(self, amount: str | float | int, currency: str, expected: str) -> None:
        assert format_money(amount, currency) == expected

    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [
            ("99.99", "USD", "$99.99 USD"),
            ("1000", "USD", "$1,000.00 USD"),
            (50, "USD", "$50.00 USD"),
        ],
    )
    def test_usd(self, amount: str | float | int, currency: str, expected: str) -> None:
        assert format_money(amount, currency) == expected

    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [
            ("1500.00", "GBP", "\u00a31,500.00 GBP"),
            ("100.00", "EUR", "\u20ac100.00 EUR"),
            ("999.00", "NZD", "NZ$999.00 NZD"),
            ("250.00", "CAD", "C$250.00 CAD"),
            ("1000.00", "CHF", "CHF 1,000.00 CHF"),
            ("5000.00", "INR", "\u20b95,000.00 INR"),
            ("750.00", "SGD", "S$750.00 SGD"),
            ("2000.00", "HKD", "HK$2,000.00 HKD"),
        ],
    )
    def test_other_currencies(self, amount: str, currency: str, expected: str) -> None:
        assert format_money(amount, currency) == expected

    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [
            (1000, "JPY", "\u00a51000 JPY"),
            ("5000", "JPY", "\u00a55000 JPY"),
            (1500.0, "JPY", "\u00a51500 JPY"),
            (999, "KRW", "\u20a9999 KRW"),
            (10000, "VND", "10000 VND"),
        ],
    )
    def test_zero_decimal_currencies(self, amount: str | float | int, currency: str, expected: str) -> None:
        assert format_money(amount, currency) == expected

    def test_none_amount(self) -> None:
        assert format_money(None, "AUD") == "? AUD"

    def test_none_amount_usd(self) -> None:
        assert format_money(None, "USD") == "? USD"

    def test_invalid_amount_string(self) -> None:
        assert format_money("not-a-number", "AUD") == "not-a-number AUD"

    def test_unknown_currency_no_symbol(self) -> None:
        assert format_money("100.00", "XYZ") == "100.00 XYZ"

    def test_negative_amount(self) -> None:
        assert format_money("-500.00", "AUD") == "A$-500.00 AUD"

    def test_zero(self) -> None:
        assert format_money("0.00", "AUD") == "A$0.00 AUD"

    def test_large_amount(self) -> None:
        assert format_money("10000000.00", "AUD") == "A$10,000,000.00 AUD"

    def test_small_decimal(self) -> None:
        assert format_money("0.01", "AUD") == "A$0.01 AUD"

    def test_currency_symbols_defined(self) -> None:
        """Verify all expected currencies have symbols."""
        assert "AUD" in CURRENCY_SYMBOLS
        assert "USD" in CURRENCY_SYMBOLS
        assert "GBP" in CURRENCY_SYMBOLS
        assert "EUR" in CURRENCY_SYMBOLS
        assert "JPY" in CURRENCY_SYMBOLS

    def test_zero_decimal_set(self) -> None:
        assert "JPY" in ZERO_DECIMAL_CURRENCIES
        assert "KRW" in ZERO_DECIMAL_CURRENCIES
        assert "VND" in ZERO_DECIMAL_CURRENCIES
        assert "AUD" not in ZERO_DECIMAL_CURRENCIES


# ===========================================================================
# Token scrubbing
# ===========================================================================


class TestScrubSecrets:
    def test_scrubs_bearer_token(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test.sig"
        result = scrub_secrets(text)
        assert "Bearer" not in result or "****" in result
        assert "eyJ" not in result

    def test_scrubs_bearer_lowercase(self) -> None:
        text = "bearer abc123xyz"
        result = scrub_secrets(text)
        assert "abc123xyz" not in result
        assert "****" in result

    def test_scrubs_jwt(self) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature_here"
        result = scrub_secrets(f"Token: {jwt}")
        assert "eyJ" not in result
        assert "****" in result

    def test_scrubs_long_hex_string(self) -> None:
        hex_str = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        result = scrub_secrets(f"Secret: {hex_str}")
        assert hex_str not in result
        assert "****" in result

    def test_scrubs_hex_40_chars(self) -> None:
        hex_str = "a" * 40
        result = scrub_secrets(hex_str)
        assert hex_str not in result

    def test_preserves_short_hex(self) -> None:
        """Hex strings under 32 chars should not be scrubbed."""
        short = "a1b2c3d4e5f6a7b8"
        result = scrub_secrets(f"ID: {short}")
        assert short in result

    def test_preserves_normal_text(self) -> None:
        text = "Contact updated successfully for Acme Corp"
        assert scrub_secrets(text) == text

    def test_preserves_empty_string(self) -> None:
        assert scrub_secrets("") == ""

    def test_scrubs_multiple_patterns(self) -> None:
        text = "Bearer mytoken123 and eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
        result = scrub_secrets(text)
        assert "mytoken123" not in result
        assert "eyJ" not in result

    def test_scrubs_in_error_message(self) -> None:
        secret = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        text = f"Token exchange failed: client_secret={secret}"
        result = scrub_secrets(text)
        assert "a1b2c3d4e5f6" not in result

    def test_scrubs_xero_token_response(self) -> None:
        header = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjFDQUNFOTk2M0IyQjYxMkI0QkIyRUQ5OEIzRUExNzVCQ0I2MkE4RTci"
        jwt = f"{header}.eyJuYmYiOjE3MTEwMDAwMDB9.sig123"
        text = f"access_token: Bearer {jwt}"
        result = scrub_secrets(text)
        assert "eyJhbGciOiJSUzI1NiI" not in result
