# xero-blade-mcp

Xero Accounting + Payroll AU MCP server for Claude and other LLM agents. Token-efficient, security-first, Sidereal-native.

53 tools covering contacts, invoices, bills, bank transactions, payments, credit notes, purchase orders, quotes, manual journals, chart of accounts, financial reports, tax rates, currencies, tracking categories, payroll employees, timesheets, payslips, and webhook verification.

## Why another Xero MCP?

The [official Xero MCP](https://github.com/XeroAPI/xero-mcp-server) is a raw API passthrough. It returns complete JSON payloads (800+ tokens per list response), has no write protection, no credential scrubbing, and no published test suite. Community alternatives are either expense-only, read-only (SQL), or limited to 4-16 tools.

xero-blade-mcp is purpose-built for LLM agents operating on financial data:

- **SecOps** -- Mandatory write gating, confirm gate for destructive operations (void, delete, archive), credential scrubbing in all error paths, OAuth2 token auto-refresh with secure local storage
- **Token efficiency** -- Pipe-delimited lists, field selection, human-readable money (A$150.00 AUD), null-field omission, date formatting, pagination hints -- not raw JSON dumps
- **Sidereal ecosystem** -- `accounting-v1` contract, plugin manifest, webhook HMAC-SHA256 verification for dispatch integration, HTTP transport mode for daemon routing

## Comparison

| Capability | xero-blade-mcp | XeroAPI/xero-mcp-server | john-zhang-dev/xero-mcp |
|---|---|---|---|
| Tools | 53 | 50+ | 16 |
| Token-efficient responses | Pipe-delimited, field selection, summarised | Raw JSON (full objects) | Raw JSON |
| Write gating | Per-operation env var gate | None | None |
| Destructive op confirmation | `confirm=true` required for void/delete/archive | None | None |
| Credential scrubbing | JWT, Bearer, hex token scrubbing | None | None |
| Rate limiting | Built-in (60/min, 5 concurrent, 429 retry) | None | None |
| Payroll AU | Employees, timesheets, payslips | Claimed | None |
| Webhook HMAC verification | Built-in tool (HMAC-SHA256) | None | None |
| Reports | P&L, Balance Sheet, Trial Balance, Aged AR/AP | Yes | Limited |
| Multi-tenant | XERO_TENANT_ID + discovery tool | Yes | Yes |
| Auth modes | Custom Connection + PKCE + static token | Custom Connection + Bearer | OAuth2 |
| Tests | 413 unit tests | Undisclosed | Partial |
| Sidereal integration | accounting-v1 contract, plugin manifest | None | None |
| Runtime | Python (uv) | Node.js (npx) | Node.js |

### Token efficiency: before and after

**XeroAPI/xero-mcp-server** (raw JSON, ~1200 tokens):
```json
{"Invoices":[{"InvoiceID":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","InvoiceNumber":"INV-0001","Type":"ACCREC","Contact":{"ContactID":"f1e2d3c4-b5a6-7890-fedc-ba0987654321","Name":"Acme Corp","ContactStatus":"ACTIVE","EmailAddress":"billing@acme.com","IsCustomer":true,"IsSupplier":false},"DateString":"2026-03-15T00:00:00","DueDateString":"2026-04-14T00:00:00","Status":"AUTHORISED","SubTotal":1500.00,"TotalTax":150.00,"Total":1650.00,"AmountDue":1650.00,"AmountPaid":0.00,"CurrencyCode":"AUD","LineItems":[{"Description":"Consulting services - March 2026","Quantity":10.0,"UnitAmount":150.00,"LineAmount":1500.00,"AccountCode":"200","TaxType":"OUTPUT"}]}]}
```

**xero-blade-mcp** (pipe-delimited, ~60 tokens):
```
INV-0001 | Acme Corp | AUTHORISED | A$1,650.00 AUD | 2026-04-14 | due=A$1,650.00 AUD
```

**16x fewer tokens** for the same information. For a P&L report the savings are even larger -- structured table output vs nested JSON arrays.

## Quick start

```bash
# Install
uv tool install xero-blade-mcp

# Configure (Custom Connection -- recommended)
export XERO_CLIENT_ID="your_client_id"
export XERO_CLIENT_SECRET="your_client_secret"
export XERO_TENANT_ID="your_tenant_id"

# Run
xero-blade-mcp
```

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "xero": {
      "command": "uvx",
      "args": ["xero-blade-mcp"],
      "env": {
        "XERO_CLIENT_ID": "your_client_id",
        "XERO_CLIENT_SECRET": "your_client_secret",
        "XERO_TENANT_ID": "your_tenant_id"
      }
    }
  }
}
```

### HTTP transport (remote/tunnel access)

```bash
export XERO_MCP_TRANSPORT="http"
export XERO_MCP_HOST="127.0.0.1"
export XERO_MCP_PORT="8770"
export XERO_MCP_API_TOKEN="your-bearer-token"  # optional, enables auth
xero-blade-mcp
```

## Authentication

Three modes, in priority order:

| Mode | Env Vars | Use Case |
|---|---|---|
| **Static token** | `XERO_ACCESS_TOKEN` | Testing, short-lived (30 min expiry) |
| **Custom Connection** | `XERO_CLIENT_ID` + `XERO_CLIENT_SECRET` | Production MCP (recommended, auto-refresh) |
| **Stored tokens** | `XERO_CLIENT_ID` | After initial PKCE flow, tokens at `~/.xero-blade-mcp/tokens.json` |

### Setting up a Custom Connection

1. Go to [developer.xero.com](https://developer.xero.com) and create a new app
2. Select "Custom connection" as the app type
3. Select the organisation to connect
4. Grant scopes: `accounting.transactions`, `accounting.contacts`, `accounting.settings`, `accounting.reports.read`, `payroll.employees`, `payroll.timesheets`, `payroll.payslips`
5. Note the Client ID and Client Secret
6. Use `xero_connections` tool to find your Tenant ID

## Security model

### Write gate

All create, update, delete, and void operations require `XERO_WRITE_ENABLED=true`. Without it, the server is read-only.

### Confirm gate

Destructive operations that are difficult to reverse require `confirm=true` as a parameter:

| Operation | Gate |
|---|---|
| `xero_archive_contact` | write + confirm |
| `xero_void_invoice` | write + confirm |
| `xero_void_bill` | write + confirm |
| `xero_delete_payment` | write + confirm |
| `xero_void_credit_note` | write + confirm |
| `xero_approve_timesheet` | write + confirm |

### Credential scrubbing

All error messages are scrubbed of:
- JWT tokens (`eyJ...` patterns)
- Bearer authorization headers
- Long hexadecimal strings (OAuth tokens, secrets)

### Rate limiting

Built-in rate limiter respects Xero's API limits:
- 60 API calls per minute per tenant
- 5 concurrent requests
- Automatic retry on 429 with Retry-After header

## Configuration

| Variable | Required | Description |
|---|---|---|
| `XERO_CLIENT_ID` | Yes* | OAuth2 client ID |
| `XERO_CLIENT_SECRET` | Yes* | OAuth2 client secret (Custom Connection) |
| `XERO_TENANT_ID` | Recommended | Active organisation tenant ID |
| `XERO_ACCESS_TOKEN` | No | Pre-obtained access token (overrides OAuth) |
| `XERO_WRITE_ENABLED` | No | Set to `true` to enable write operations |
| `XERO_WEBHOOK_KEY` | No | Webhook signing key for HMAC verification |
| `XERO_MCP_TRANSPORT` | No | `stdio` (default) or `http` |
| `XERO_MCP_HOST` | No | HTTP host (default: `127.0.0.1`) |
| `XERO_MCP_PORT` | No | HTTP port (default: `8770`) |
| `XERO_MCP_API_TOKEN` | No | Bearer token for HTTP transport auth |

\* Either `XERO_CLIENT_ID` + `XERO_CLIENT_SECRET` or `XERO_ACCESS_TOKEN` required.

## Tools

### Meta (3 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_info` | Connection status, active tenant, config | R |
| `xero_connections` | List connected tenants/organisations | R |
| `xero_organisation` | Organisation details, currency, tax settings | R |

### Contacts (5 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_contacts` | List contacts with search, status filter | R |
| `xero_contact` | Contact detail with field selection | R |
| `xero_create_contact` | Create contact | W |
| `xero_update_contact` | Update contact fields | W |
| `xero_archive_contact` | Archive contact (confirm required) | W+C |

### Invoices (6 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_invoices` | List sales invoices with filters | R |
| `xero_invoice` | Invoice detail with line items, payments | R |
| `xero_create_invoice` | Create sales invoice | W |
| `xero_update_invoice` | Update draft/submitted invoice | W |
| `xero_void_invoice` | Void invoice (confirm required) | W+C |
| `xero_email_invoice` | Email invoice to contact | W |

### Bills (4 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_bills` | List purchase bills | R |
| `xero_bill` | Bill detail with line items | R |
| `xero_create_bill` | Create purchase bill | W |
| `xero_void_bill` | Void bill (confirm required) | W+C |

### Bank Transactions (3 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_bank_transactions` | List bank transactions | R |
| `xero_bank_transaction` | Transaction detail | R |
| `xero_create_bank_transaction` | Create spend/receive transaction | W |

### Payments (4 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_payments` | List payments | R |
| `xero_payment` | Payment detail | R |
| `xero_create_payment` | Record payment against invoice/bill | W |
| `xero_delete_payment` | Delete payment (confirm required) | W+C |

### Credit Notes (3 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_credit_notes` | List credit notes | R |
| `xero_create_credit_note` | Create credit note | W |
| `xero_void_credit_note` | Void credit note (confirm required) | W+C |

### Purchase Orders (2 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_purchase_orders` | List purchase orders | R |
| `xero_create_purchase_order` | Create purchase order | W |

### Quotes (2 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_quotes` | List quotes | R |
| `xero_create_quote` | Create quote | W |

### Accounts (2 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_accounts` | Chart of accounts with type/class filter | R |
| `xero_account` | Account detail | R |

### Manual Journals (1 tool)

| Tool | Description | R/W |
|---|---|---|
| `xero_manual_journals` | List manual journal entries | R |

### Reports (5 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_profit_loss` | P&L report with date range, periods | R |
| `xero_balance_sheet` | Balance sheet as at date | R |
| `xero_trial_balance` | Trial balance as at date | R |
| `xero_aged_receivables` | Aged receivables with breakdown | R |
| `xero_aged_payables` | Aged payables with breakdown | R |

### Reference Data (4 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_tax_rates` | Tax rates and effective percentages | R |
| `xero_currencies` | Active currencies | R |
| `xero_tracking_categories` | Tracking categories and options | R |
| `xero_branding_themes` | Branding themes for documents | R |

### Payroll AU (8 tools)

| Tool | Description | R/W |
|---|---|---|
| `xero_employees` | List payroll employees | R |
| `xero_employee` | Employee detail (tax, super, leave) | R |
| `xero_timesheets` | List timesheets | R |
| `xero_timesheet` | Timesheet detail with lines | R |
| `xero_create_timesheet` | Create timesheet | W |
| `xero_approve_timesheet` | Approve timesheet (confirm required) | W+C |
| `xero_payslips` | List payslips for a pay run | R |
| `xero_payslip` | Payslip detail (earnings, deductions, super) | R |

### Webhooks (1 tool)

| Tool | Description | R/W |
|---|---|---|
| `xero_verify_webhook` | HMAC-SHA256 signature verification | R |

## Development

```bash
# Setup
git clone https://github.com/groupthink-dev/xero-blade-mcp.git
cd xero-blade-mcp
make install-dev

# Test
make test           # 413 unit tests
make test-cov       # with coverage report

# Quality
make lint           # ruff linter
make format         # ruff formatter
make type-check     # mypy
make check          # all of the above
```

## Sidereal integration

Implements the `accounting-v1` service contract. Registered in the [Sidereal Plugin Registry](https://github.com/groupthink-dev/sidereal-plugin-registry).

```yaml
# sidereal-plugin.yaml
contract: accounting-v1
tier: certified
tools: 53
```

## Xero API scope requirements

| Scope | APIs Covered |
|---|---|
| `accounting.transactions` | Invoices, Bills, Bank Transactions, Payments, Credit Notes, POs, Quotes |
| `accounting.contacts` | Contacts |
| `accounting.settings` | Accounts, Tax Rates, Currencies, Tracking, Branding |
| `accounting.reports.read` | P&L, Balance Sheet, Trial Balance, Aged AR/AP |
| `payroll.employees` | Employees |
| `payroll.timesheets` | Timesheets |
| `payroll.payslips` | Pay Runs, Payslips |

## License

MIT
