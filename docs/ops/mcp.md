# MCP tool server

BigBound exposes a **read-only** slice of the collections tool catalog to an
external agent (Cursor, Claude, a bank copilot). It is a product surface, not a
debug sidecar.

## How to run — stdio

```text
pip install -r requirements-mcp.txt
python -m mcp_server
```

Point the MCP client at that command. The process boundary **is** the auth
boundary. `MCP_API_KEY` is unused on stdio.

## How to run — HTTP (Phase 3)

A **separate** Starlette process. Not mounted on FastAPI.

```text
MCP_HTTP_ENABLED=true
MCP_TRANSPORT=http
MCP_API_KEY=<scoped bootstrap key>
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=8081
python -m mcp_server
```

`MCP_API_KEY` is required. The bootstrap key is `crm.read`, `kb.search`,
`offers.read`, `policy.read` — never `tasks.write`, never mutators. Mint
narrower keys from Integrations → Our MCP (`POST /mcp/keys`).

Headers on every response: `Mcp-Method`, `Mcp-Name`, `Mcp-Protocol-Version`.
No sticky `Mcp-Session-Id` for reads.

mTLS for anything off-loopback:

```text
MCP_TLS_CERTFILE=...
MCP_TLS_KEYFILE=...
MCP_TLS_CAFILE=...   # CERT_REQUIRED when set
```

Auth: `Authorization: Bearer <key>` or `X-MCP-Key`.

## Why it is not on FastAPI

`mcp_server.py` is a separate process on purpose:

1. `ApiKeyMiddleware` is `BaseHTTPMiddleware` and does not cleanly support ASGI
   SSE/WebSocket scopes.
2. `GZipMiddleware` would compress and buffer a `text/event-stream`.
3. Exempting `/mcp` from auth to work around (1) would put CRM tools on the
   public API unauthenticated.

Do not mount this on the FastAPI app "to make it simpler."

## What it can do

The five tools with `CHANNEL_MCP` in `agent_core/tools/catalog.py`:

- `get_customer_context`
- `get_payment_history`
- `get_emi_schedule`
- `check_product_eligibility`
- `search_knowledge_base`

Every mutating tool (`create_promise_to_pay`, `apply_goodwill`, `flag_dispute`,
…) is on an explicit deny-list and returns **403** `mutating_tools_denied`.
`tests/test_mcp_catalog.py` is the contract: adding a mutator to the MCP
surface fails CI. `enqueue_task` is HTTP-only when `MCP_TASKS_ENABLED` and the
key has `tasks.write` — it is **not** in `CHANNEL_MCP`.

Resources (scoped): `customer://`, `account://{id}/ledger`, `kb://snapshot/{id}`,
`interaction://{id}/trace`, `policy://authority-matrix`.

Prompts (user-triggered, no sampling): `prep_handoff`, `draft_ptp_sms`.

Tasks: `enqueue_task` returns a ticket id. The KB worker drains
`mcp_tasks` into `request_documents`. The mouth never waits.

Audit rows go to `bot_tool_calls` with `channel='mcp'`.

## Client (us calling tenants)

First-party connectors `ext.paylink.get_status` and `ext.lms.get_balance` read
real `payment_intents` / customer outstanding. Remote MCP URLs must be HTTPS,
approved, data-classed, and vault-ref authenticated. Idle mouth **excludes**
`ext.*` so G6 does not blow the 12-tool cap. Compiler G10 binds them.

## What it cannot do

- Writes. There is no identity-verification ceremony on MCP. Until MRTR
  elicitation or a floor confirm exists, mutating tools stay denied.
- MCP Apps UI (`MCP_APPS_ENABLED` is schema/flag only — Phase 5).
- Arbitrary HTTP MCP URL on a voice card without data-class review.
- Tokens in `.env` for connector OAuth — those live in `vault_refs`.

See `agent_transformation_implementation.md` Phase 3.
