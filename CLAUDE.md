# xero-blade-mcp — Development Context

Xero Accounting + Payroll AU MCP server for the Sidereal ecosystem.

## Architecture

- `src/xero_blade_mcp/models.py` — constants, write/confirm gates, money formatting, credential scrubbing
- `src/xero_blade_mcp/auth.py` — OAuth2 Custom Connection + PKCE, token storage (~/.xero-blade-mcp/tokens.json), auto-refresh
- `src/xero_blade_mcp/client.py` — async httpx client, rate limiter (60/min, 5 concurrent), Accounting + Payroll AU API methods
- `src/xero_blade_mcp/formatters.py` — pipe-delimited output, Xero /Date() parsing, field selection, page hints
- `src/xero_blade_mcp/server.py` — FastMCP server, 53 tools with write gating and confirm gates

## Key Patterns

- **Write gate:** `XERO_WRITE_ENABLED=true` env var required for any mutation
- **Confirm gate:** `confirm=true` parameter required for void/delete/archive operations
- **Token efficiency:** Pipe-delimited lists, null omission, human money (A$150.00 AUD), short dates
- **OAuth2:** Priority: XERO_ACCESS_TOKEN > XERO_CLIENT_ID+SECRET > stored tokens
- **Rate limiting:** 60 calls/min, 5 concurrent, auto-retry on 429 with Retry-After
- **Multi-tenant:** XERO_TENANT_ID selects active org, xero_connections tool lists tenants

## Testing

```bash
make test          # 413 unit tests
make test-cov      # with coverage
make check         # lint + format + type-check
```

## Contract

Implements `accounting-v1` in the sidereal-plugin-registry.
