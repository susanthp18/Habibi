# 11 — API contracts

**Role:** API contract governance architect.
**Scope:** the HTTP surface between `backend/` and `Habibi/src`. Guest tree `PRAXIST-main/` is out of scope.
**Date:** 2026-09-02
**Mode:** read-only. No product code was changed except this file.
**Companions:** `14-error-handling.md` (failure semantics — the error section here is deliberately narrower), `09-canonical-implementations.md` (how this repo picks an owner), `12-data-model.md`, `04-backend-architecture.md`, `03-frontend-architecture.md`, `06-duplication.md`.
**Vocabulary:** `CONTEXT.md`. Terms in **bold** are that glossary.

**Method:** five analysts — FastAPI routes, frontend consumers, schemas, validation, error contracts — then every headline claim re-read from source by this document. Route counts were re-derived here by parsing all 314 decorators (including the three multi-line and one double-stacked) rather than taken from any analyst. Where an analyst's hypothesis was disproved, it is recorded in *Checked and cleared* rather than dropped. Git history cannot support drift-over-time claims: only nine commits touch `main.py`, and they are squashed snapshots ("Hackathon submission snapshot", "baseline before autonomous development"). Everything below is sourced from the code.

---

## Verdict

**This codebase has a contract. It has no mechanism that keeps the contract true.**

The pieces are unusually good. There is one canonical schema module (`schemas.py`, 247 models), not schemas scattered through handlers — `main.py` declares zero `BaseModel`. There is one frontend client (`config.ts`), and 42 of the 43 consumer modules go through it. Authorization coverage is CI-enforced complete. Pagination is bounded almost everywhere. Pydantic v2 is used consistently, with no v1 residue anywhere. Nothing in this audit found a dead frontend call, a duplicate route, or a path-shadowing bug — three failure modes a 314-route single-file FastAPI app is entitled to have.

What is missing is the gate. And the repository already knows exactly how to build one, because it built one — for the database:

```
.github/workflows/backend-pytest.yml
  → derives expected tables/columns from op.create_table / op.add_column
  → fails if sql/*.sql is behind Alembic          ("idempotency_keys was missing this way")
  → tests/test_schema_parity.py catches the reverse direction
```

That is a real drift gate, in both directions, with a named incident behind it. The HTTP contract — the boundary that a browser, a carrier and a bank all sit on the far side of — has nothing equivalent. What it has instead is **five hand-written tests, each pinning one payload shape, each written after a specific outage**: `test_agent_card_schema_drift.py`, `test_inbox_channel_contract.py`, `test_place_contract.py`, `test_reco_contracts.py`, `test_sandbox_turn_schema.py`.

This is the pattern `14-error-handling.md` named in its own domain, arriving here independently: **the thinking happened per incident rather than per seam.** Each gate landed exactly where the pain was and did not generalize by one inch. The defects below are, without exception, in the places the incidents have not reached yet.

Three findings carry the report:

1. **`requestedVia` on a document request is fabricated by the API.** Three routes report a hardcoded `"voice"` for a column whose real value they select and discard. On a regulated collections platform, this is the audit field answering *who asked for this document*. (P0, §2)
2. **`GET /billing` models tenancy as client input** while every other route in the system models it as process configuration. The route is IDOR-shaped; it is inert only because one tenant is seeded. (P0-by-shape, §3)
3. **OpenAPI is not authoritative here, and is not served in production at all.** It is a byproduct, and 57% of routes do not even contribute a response shape to it. (§5)

---

## 1. The contract triangle

Every wire vocabulary in this system is declared in three places, in three languages, with no link between them:

```
   sql/*.sql  CHECK (col IN (...))          ← the only one the database enforces
        │
        │  test_inbox_channel_contract.py guards this leg — for ONE column
        ▼
   schemas.py  Literal[...]                 ← what FastAPI validates responses against
        │
        │  test_agent_card_schema_drift.py guards this leg — for ONE model
        ▼
   Habibi/src  TS union / as const          ← what the UI branches on
```

Both existing tests guard **one leg each, for one thing each**. Neither closes the triangle, and no third test exists. Every vocabulary defect in this report sits where the triangle is open.

The two tests are also better than their coverage suggests, which is the argument for generalizing rather than replacing them. `test_inbox_channel_contract.py` reads the CHECK constraint out of `sql/04_interactions.sql` at test time and holds the Pydantic `Literal` to it — the database is treated as the authority, correctly, because it is what actually decides which values can exist. `test_agent_card_schema_drift.py` regex-reads an `as const` array out of the TypeScript and compares it to `AgentCard.model_fields` and to `ROLLBACK_TRIGGERS`. Both mechanisms are cheap, dependency-free, and already proven in CI.

`test_agent_card_schema_drift.py` also has a hole worth fixing in the same pass: it lives in the backend job, which is `paths:`-filtered to `backend/**`. The frontend job is filtered to `Habibi/**` and runs only `tsc`, `vitest` and `eslint`. **Editing `Habibi/src/api/agent-card.ts` alone never runs the test that guards it.**

---

## 2. P0 — the API fabricates document provenance

The one defect in this report that is wrong today, in the deployed configuration, with no second tenant or future refactor required.

**The trace, end to end:**

```
Habibi/src/api/documents.ts:58        POST /document-requests { requestedVia: "agent", ... }
  → main.py:1639                      response_model=DocumentRequestResponse
  → schemas.py:1082                   DocumentRequestCreateRequest.requestedVia
                                        Literal["bot_voice","bot_chat","agent"] | None
  → db.py:6268                        requested_via = payload.get("requestedVia") or "agent"
                                        validated against the 7-value set, written correctly
  → sql/17_phase4.sql:25-30           CHECK IN (bot_voice, bot_chat, agent, mcp, clerk, vision, inbox)   ✓ row is right
  → db.py:6328                        response = _document_by_id(...) → _document_contracts(...)
  → db.py:1441                        SELECT ... requested_via, source FROM document_requests
  → db.py:1455                        "requestedVia": "voice",          ✗ THE COLUMN IS DISCARDED
  → schemas.py:136                    DocumentRequestResponse.requestedVia: Channel
  → schemas.py:28                       Channel = Literal["voice","whatsapp","chat","email","sms"]
  → Habibi/src/components/customer360/DocumentsTab.tsx:64   CHANNEL_ICON[d.requestedVia]
```

`db.py:1435-1462` selects `requested_via` at line 1441 and never reads it. The sibling key four lines below the hardcode — `source`, `db.py:1459` — *is* read from the row (`r.get("source") or "crm"`), and it was selected by the same `SELECT`. A dead column read beside a live one, in one dict literal, is not a design; it is a wire that was cut to make a too-narrow type validate.

**Three routes return the fabricated value, one returns the truth:**

| Route | `response_model` | Reports | Source |
|---|---|---|---|
| `POST /document-requests` (`main.py:1639`) | `DocumentRequestResponse` | always `"voice"` | `db.py:1455` |
| `PATCH /document-requests/{id}` (`main.py:1679`) | `DocumentRequestResponse` | always `"voice"` | `db.py:1455` |
| `GET /customers/{id}` → `.documents[]` (`schemas.py:170`) | `DocumentRequestResponse` | always `"voice"` | `db.py:1455` |
| `GET /document-requests` (`main.py:1671`) | `DocumentListResponse` | **the real column** | `_doc_requested_via`, `db.py:844-860` |

So the Document Fulfilment Desk and Customer 360 disagree about the same row. The Desk branches on the true value (`RequestsTable.tsx:171-177`, `RequestSheet.tsx:58`, on `bot_voice`/`bot_chat`/`agent`); Customer 360 looks the fabricated value up in a map keyed by the **Channel** vocabulary and shows the voice icon for every document ever requested — by a clerk, by the vision pipeline, by MCP, by a human agent.

**Why it is shaped this way** — the three declarations of one field are mutually disjoint:

| Declaration | Vocabulary |
|---|---|
| `schemas.py:136` `DocumentRequestResponse.requestedVia: Channel` | `voice, whatsapp, chat, email, sms` |
| `schemas.py:1082` `DocumentRequestCreateRequest.requestedVia` | `bot_voice, bot_chat, agent` |
| `schemas.py:1136` `DocumentListResponse.requestedVia` | `bot_voice, bot_chat, agent, mcp, clerk, vision, inbox` |

The request model can only accept values the response model can never emit — their intersection is empty. The database agrees with the third and with neither of the first two: `sql/05_collections.sql:166` carried the 3-value CHECK and `sql/17_phase4.sql:25-30` **already widened it to all seven**, while `schemas.py:1082` stayed pinned to the pre-widening set and `schemas.py:136` was typed against an unrelated vocabulary entirely.

Without the hardcode at `db.py:1455` this would be `test_inbox_channel_contract.py`'s outage verbatim — a `Literal` narrower than its CHECK constraint, `ResponseValidationError`, a 500, a dead screen. That test was written because that outage happened. Two models away, the same defect was instead papered over with a literal, and so it fails silently. **That is worse:** a 500 is reported; a fabricated audit field is believed.

**Canonical candidate:** `DocumentListResponse.requestedVia` (`schemas.py:1136`) — it is the only one of the three that matches the CHECK constraint. `DocumentRequestResponse.requestedVia` should be retyped to it, `schemas.py:1082` widened to it, the three declarations collapsed into one `RequestedVia` alias beside `Channel` at `schemas.py:28`, and `db.py:1455` should return the column it already reads. `Channel` is a different question and must not absorb this one — see *Do not merge* below.

---

## 3. P0-by-shape — `GET /billing` models tenancy as client input

```
main.py:1018   tenantId: str = Query("all"),      → db.billing_overview(period, tenantId, env)
main.py:1070   tenantId: str = Query("all"),      → db.billing_export_csv(period, tenantId, env)
```

`db.billing_overview` (`db.py:16766`) checks only that the supplied tenant **exists** (`db.py:16782-16788`, `raise ValueError(f"unknown_tenant: {tenant_id}")`) and then uses it directly as a SQL filter (`AND tenant_id = :tenant_id`). It never compares it to the caller's own tenant. These queries are built with `text()`, not `_sql()`, so the customer-visibility predicate (`db.py:241-255`) does not apply — and would not be the right instrument anyway, since it scopes customer rows, not tenants. Authorization is `BILLING_READ` (`authz.py:256-257`), which is role-based, not tenant-scoped. The default `"all"` means the unmodified request reads across every tenant.

It is a first-class UI control, not a latent parameter: `Habibi/src/routes/billing.tsx:45` holds `tenantId` in `useState` and `Habibi/src/api/billing.ts:91,141` put it into the query string for both the JSON fetch and the CSV export.

**Stated precisely, because the ranking depends on it:** this is not exploitable in the current deployment. `sql/09_bot_config.sql:393` seeds exactly one tenant, and `tenant_context.py:1-14` says the design is deliberately one-process-one-tenant — `db.TENANT_ID` is a process-wide constant read from the environment at import time, and the module exists as a dormant seam for the day a request can carry its own tenant. The finding is that **the route has already crossed that seam and nothing else has.** It is the only place in `main.py` where a tenant/org/workspace identifier is taken from the request (verified by grep; no other instance exists). The contract defect is the inconsistency itself: one route says tenancy is a request concept, and the other 313 say it is deployment configuration. Whichever is right, they cannot both be.

The security framing belongs to a security review; the governance framing is that this is the single route that would silently start leaking on the day a second tenant is onboarded, with no code change on the caller's side.

---

## 4. The end-to-end map

The objective was to trace frontend request → route → request schema → service → response schema → frontend consumer. Two traces, chosen because they fail differently, plus the document-request trace already given in §2.

### Trace 1 — a customer with no minimum due

```
Habibi/src/api/customers.ts:28     apiGet<Customer[]>("/customers")
  → main.py:941                    GET /customers, response_model=list[CustomerResponse]
  → db.py:1081                     _customer_contract() → CustomerResponse
  → schemas.py:158-159             minimumDue: float | None = None
                                   lastContact: str | None = None
  → Habibi/src/data/customer360-seed.ts:135-136
                                   minimumDue: number;      ✗ non-nullable
                                   lastContact: string;     ✗ non-nullable
```

The backend is honest and the frontend type is a lie. `null` arrives, TypeScript has asserted `number`, and nothing fails at the boundary — the error surfaces later as a formatting or arithmetic result nobody traced back here. Note also where the type lives: `Customer` is imported into `api/customers.ts:14` **from `@/data/customer360-seed`**, the mock data file, and used to parse live API responses at `:28` and `:33`. The mock's shape is the production contract.

### Trace 2 — publishing a **Mouth** whose card fails a **Gate**

```
Habibi/src/api/prompt-studio.ts:1033   usePublishStudioDraft()  → POST /prompt-versions/{id}/publish
  → main.py:3117-3134                  except CompileError → HTTPException(detail=exc.http_detail())
  → agent_core/cards/compile.py:107    {"code": "compile_failed", "status": ..., "report": {...gates...}}
  → Habibi/src/api/config.ts:89-112    errorDetail(): detail is not a string
                                         → JSON.stringify(payload.detail).slice(0, 400)
  → prompt-studio.lazy.tsx:986         toast.error(err.message)
```

This is the richest, most deliberately designed error shape in the codebase — a machine-readable `code` plus the full **Gate** report — and it is `JSON.stringify`'d into a truncated blob in a toast. The component that knows how to render a `CompileReport` exists (`PublishDialog.tsx:100`, `compileReport?.gates ?? []`) but is fed from a *different*, success-path endpoint (`POST /agent-studio/cards/{bot_id}/compile`, `main.py:2099`). `usePublishStudioDraft()` has no `onError`. So the operator sees a JSON fragment where the gate list they get from a normal compile check would have been. **Structure is authored at one end of the wire and discarded at the other because the envelope has no place to put it.**

---

## 5. Is OpenAPI authoritative? — No. It is a byproduct, and in production it does not exist.

Decisive, on the evidence:

| Signal | Finding |
|---|---|
| Schema served in production | **No.** `main.py:588-590` — `docs_url`, `redoc_url` and `openapi_url` are all `None if _IS_PROD` |
| Committed `openapi.json` / `.yaml` | **None**, anywhere in the repo |
| Codegen from the spec | **None.** No `openapi`/`orval`/`swagger`/`zodios` in `Habibi/package.json` or `Habibi/src`; no generated directory |
| CI gate on contract shape | **None.** Two workflows: `backend-pytest.yml` (ruff, schema-parity, pytest) and `frontend-typecheck.yml` (tsc, vitest, eslint) |
| `response_model=` coverage | **136 / 314 (43%).** Absent on 178 — POST 83, GET 78, PATCH 9, DELETE 6, WS 2 |
| `tags=` | **0 of 314** |
| `summary=` / `operation_id=` | **0 / 0** |
| `include_in_schema=False` | 1 (`GET /metrics`, `main.py:927`) |
| App metadata | `title` + `version="0.1.0"` only (`main.py:581-591`). No `description`, `servers`, `contact`, `openapi_tags` |
| API versioning | **None of any kind.** 0 routes under a `/v1`-style prefix; no `X-API-Version`/`Accept-Version`; 0 `deprecated=`; no `Deprecation`/`Sunset` headers |

The last row is its own finding. `version="0.1.0"` is a literal that has never moved and is not served where anyone could read it. **There is no mechanism in this system for telling a caller that something changed.** Every one of the drift defects in this report is therefore permanently undetectable from outside the process.

The generated document is worth what it costs, which is nothing — it is FastAPI's byproduct, not an artifact anyone maintains, diffs, publishes or validates against. Calling it documentation overstates it: with 57% of routes contributing no response shape and zero routes carrying a tag or summary, a reader learns the path and the method and stops.

---

## 6. Route surface

314 routes, one file, one `FastAPI()`. Zero `APIRouter`, zero `include_router` in the entire backend.

**GET 152 · POST 125 · PATCH 28 · DELETE 7 · WEBSOCKET 2 · PUT 0.**

A second HTTP surface exists and is deliberately separate: `mcp_server.py` + `agent_core/mcp_http/http_app.py:79-87`, its own process and port, one JSON-RPC endpoint, its own bearer auth (`http_app.py:20-29`), no FastAPI routing and no OpenAPI. The separation is documented (`mcp_server.py:5-24`: middleware incompatibilities with SSE). The governance consequence is real though: **two independent, unreconciled authorization systems** — `authz.ROUTE_PERMISSIONS` for the main API, its own bearer check for MCP.

| Sev | Finding | Evidence |
|---|---|---|
| P1 | **DELETE has four different response contracts across seven routes.** 204 empty (`main.py:1104`, `:4519`); 200 with ad-hoc `{"ok": True}` (`:1469`, `:5401`); 200 with whatever `_handle_write` returned, untyped (`:1931`, `:2250`); 200 with a full typed body (`:4371`, `response_model=KbDeleteDocumentResponse`). Seven routes, four shapes. Only one carries a `response_model` | above |
| P1 | **`/calls` and `/interactions` are the same entity under two nouns**, and neither can fetch one by id. `POST /interactions` (`:1539`) creates and returns `CallResponse`; the only list is `GET /calls` (`:1113`); there is no `GET /interactions/{id}` — only `/export`, `/cost`, `/trace`, `/wrap-up` sub-resources | `main.py:1030,1113,1123,1134,1539,1544` |
| P1 | **Four lexemes for "webhook"**: `/webhooks/*`, `/webhook/whatsapp`, `/webhook-endpoints` (6 routes), `/webhook-deliveries` (2 routes). No canonical noun | `main.py:825,857,1444-1486,1496-1501,4585-4601` |
| P2 | **No route in the file ever returns 201.** Only two explicit `status_code=` exist in all 314, both the 204 deletes. Every create returns 200. Uniform, but uniformly off convention | `main.py:1104`, `:4519` |
| P2 | Three shapes for one concept in the payment-webhook family: `{provider}` path param, a hardcoded `collections` segment, and a different top-level prefix | `main.py:825,857,882` |
| P2 | `ConversationListResponse` is the `response_model` for a list, a single-item GET, and three mutation POSTs | `main.py:4256,4264,4272,4277,4282` |
| P2 | Verb-in-path mixed into noun resources (`POST /kb/retrieve` beside `GET /kb/documents`); `.csv` file extension in exactly one path | `main.py:4296,4320,1067` |
| P2 | `/readyz` is exempted from auth in the MCP app but never routed — dead, misleading config | `mcp_http/http_app.py:22` vs `:82-84` |

**Checked and cleared — path shadowing.** All 314 routes were checked for the FastAPI declaration-order trap (a literal segment swallowed by an earlier `{param}` route of the same method and arity). **Zero occurrences.** Every literal precedes its parameterized sibling — `/prompt-versions/published` (`:1951`) before `/prompt-versions/{version_id}` (`:1960`); `/agent-studio/skills/scripts` (`:2213`) before `/agent-studio/skills/{skill_id}` (`:2226`). Also clean: zero duplicate `(method, path)` pairs; zero trailing-slash inconsistency; zero snake_case path segments; 47 distinct path params, all `{resource_id}`-shaped, no bare `{id}`, no abbreviations. PATCH is used for every partial update and PUT does not exist, so the usual PUT/PATCH ambiguity cannot arise. For a 314-route single-file app this is a better result than the structure predicts.

---

## 7. Schemas

`schemas.py` — 3,453 lines, **247 models**, and `main.py` declares none inline. This is a genuine canonical module, densely documented, with several docstrings naming the outage that shaped a field. **186 of 247 set `extra="forbid"`**; the 61 that do not correlate with file age — the earliest Customer 360 nested models (`schemas.py:35-149`) silently accept-and-drop unknown fields while their standalone siblings reject them.

**Duplicated DTOs.** The file deliberately keeps two shapes per entity — a thin one embedded in `CustomerResponse`, a richer one for that entity's own screen — and says so. That is a defensible pattern. It has nonetheless drifted into contract breaks:

| Concept | Embedded (Customer 360) | Standalone (screen) | Drift |
|---|---|---|---|
| **Document request** | `DocumentRequestResponse` `:133` | `DocumentListResponse` `:1116` | §2 — three disjoint `requestedVia` vocabularies, one hardcoded value. Also `type`→`docType`, `source` free-str→closed Literal |
| **Promise** | `PromiseResponse` `:103` | `PromiseListResponse` `:570` | `reminderStatus` is `{queued,sent,acknowledged,off}` at `:111`, `{off,scheduled,sent}` at `:583`, and `{off,queued,scheduled,sent,acknowledged,failed}` at `:877`. The CHECK (`sql/05_collections.sql:24`) permits all six. Also `handler` vs `owner` for one concept |
| **Dispute** | `DisputeResponse` `:119` | `DisputeListResponse` `:636` | `amount`→`disputedAmount`, `filedAt`→`capturedAt`, `type` free-str vs 6-value Literal, `assignee` optional vs required |
| **Consent** | `ConsentResponse` `:56` | `ConsentChannelResponse` `:1191` | `optedIn: bool` vs `status: Literal[4]` for one fact. The code already admits it: `ConsentChannelPatch`'s docstring (`:1157-1158`) reads *"Screen sends `status`; Customer 360 may send `optedIn`."* |

The Promise split is shipped on both sides of the wire: `Habibi/src/data/customer360-seed.ts:60` declares the four-value union and `Habibi/src/data/promises-seed.ts:13` independently declares the three-value one — the backend's split, mirrored by hand, exactly as the open triangle in §1 predicts.

**Required-but-nullable.** Thirteen fields across six response models are `X | None` with no default — required to be present, permitted to be null, which is almost never the intended contract. Only `TurnTraceResponse` (`:692-693`) documents the choice. `BotDeploymentResponse` has five (`:2342-2348`); the rest are at `:1800`, `:1811-1813`, `:2907`, `:2925-2926`.

**Casing.** No `alias_generator`, no `populate_by_name`, no `Field(alias=...)` anywhere in `backend/` — the wire format is whatever the author typed. `schemas.py` is camelCase; `agent_core/cards/schema.py` is snake_case. Both are internally consistent and both are correct for their purpose, but nothing enforces either, and they meet: `db.py:13212-13217` embeds the snake_case `AgentCard` dump as `summary["agentCard"]` inside a camelCase response, typed `dict[str, Any]` (`schemas.py:2232`), so it crosses the wire unvalidated. `main.py:2050` shows the backend special-casing its own ambiguity: `payload.get("agentCard") or payload.get("agent_card")`.

**Checked and cleared.** No Pydantic v1/v2 mixing anywhere — zero `@validator`, `class Config`, `orm_mode`, `parse_obj`, `.dict()` across the backend. No raw ORM leakage into responses: `db.py` coerces rows through `_rows()`/`_clean()` (`:370-383`) and builds real schema instances for the main entities (`_customer_contract()`, `db.py:1081`). Domain enums are `Literal`, not bare `str`.

---

## 8. Validation

Of **152 mutating routes** (POST/PATCH, including two whose decorators span lines): 70 take a typed Pydantic body, 40 legitimately take none, 9 take a raw `Request`, and **33 take `dict[str, Any]`**.

The 9 `Request` routes are not holes: 8 are inbound webhooks that need the raw bytes for HMAC verification before decoding (`main.py:832,864,3380,3488,4611`), which *is* their contract enforcement, and the ninth reads headers only. Credit where due.

The 33 are the finding. They accept arbitrary JSON with no declared schema, no unknown-key rejection, no format constraint. The five that matter most, because of what they write:

| Route | Line | Writes |
|---|---|---|
| `POST /vault/refs` | 2464 | secret material |
| `POST /vault/refs/{ref_id}/rotate` | 2476 | secret material |
| `POST /mcp/keys` | 2490 | mints API keys |
| `PATCH /roles/{role_id}/permissions` | 2857 | RBAC grants |
| `PATCH /platform/switches/{key}` | 3835 | feature flags |

None does blind `**payload` mass-assignment — each pulls named keys — but there is no length or format validation on `secret`, no `Literal` on `purpose`, and no unknown-key rejection on any of them. `PATCH /agent-studio/cards/{bot_id}` (`:2047`) is in this list too, and it writes the **Agent Card** — the one object in the system with a cross-language drift test. The card is validated later, at publish, by `extra="forbid"`; it is not validated at the route that accepts it.

**Status codes for one failure class.** The same hand-rolled "required field missing" check returns **422** in the agent-studio/MCP/roles/platform routes (`main.py:2167,2291,2302,2496,2861,3841`) and **400** in the outbound/campaigns routes (`:4892,4962,4993`). Same pattern, same author idiom, opposite codes depending on which part of the file it was written in.

**`ValueError` means two different things.** Routes funnelling through `_handle_write()` (83 call sites) map `ValueError → 409` (`main.py:732`); routes with an inline `except ValueError` map it to 400 (`:837,872,1027,1076,1091,1101,4463,4544,4577`). So `db.py:5133`'s `ValueError("provide either ownerUserId or ownerBotId, not both")` — a bad-input error — reaches the client as **409 Conflict** because `POST /promises` happens to use the helper.

**Money bounds.** Enforced only in Pydantic (no CHECK constraints on any amount column), which is fine as a single source of truth — except the siblings disagree: `PromiseCreateRequest.amount` is `gt=0` (`:868`), `PaymentPlanCreateRequest.totalAmount` is `gt=0` (`:889`), and `DisputeCreateRequest.amount` (`:897`) has **no bound at all** and accepts negatives. `PaymentPlanCreateRequest.installments` is `list[dict[str, Any]]` (`:888`) — the per-installment amounts are unvalidated everywhere.

**Checked and cleared — pagination bounds.** The expected unbounded-`limit` defect is not here. All ~45 `limit`/`offset`/`days` params use `Query(..., ge=, le=)` against `db.MAX_LIST_LIMIT` (`main.py:943-944,1115-1116,1183-1184,1248-1249,2089,2639,…`), backed by `tests/test_list_bounds.py`. One exception: `GET /mcp/tasks`'s `status: str | None = None` (`:2516`) is bare. Upload size is capped by a streaming reader (`_read_upload_capped`, `main.py:211-220`, 25MB, 413 on exceed) and filenames are sanitized (`db.py:15477`); content-type is not allowlisted (`main.py:4451`) and `chunkSize`/`overlap` (`:4433-4434`) are unbounded ints. Path params are `str` and that is correct — ids are app-minted prefixed strings, not UUIDs.

**Checked and cleared — frontend validation divergence.** There is none, because there is almost no frontend validation: `zod` appears in one file and only for a router search schema. Nothing is enforced on the client that isn't enforced on the server. The safer failure mode, at the cost of no field-level form errors anywhere.

---

## 9. The error contract

Narrower than `14-error-handling.md` by design; this section is about the *shape* as a wire contract. Its findings M1, M5, M6, H5, L6 are cited, not restated.

**`detail` is a string at 196 of 199 `HTTPException` sites, and a dict at 3** (`main.py:777`, `:3128`, `:3130`). FastAPI's automatic 422 is a third shape — an array of `{loc,msg,type}`. A client that infers "detail is a string" from 98.5% of the surface is right until readiness fails, a flow is invalid, or a card fails to compile.

The frontend survives this by accident and at a cost. `config.ts:89-112` `JSON.stringify`s any non-string `detail` and truncates to 400 characters. Nothing renders `[object Object]` — but nothing reads the structure either, which is Trace 2 in §4.

**There is no error code vocabulary at the HTTP layer.** `detail` is a human string that the client can display and not branch on. Two exceptions prove it is achievable: `CompileError.http_detail()` (`compile.py:107-112`) and `FlowInvalidError.http_detail()` (`flow_graph.py:305-313`) both carry a `code` — and both are thrown by exactly one route.

Meanwhile a *better* machine-readable error contract already exists one layer down and never reaches HTTP: `{"ok": False, "error": "<short_code>"}` in `bot_tools.py` (18 sites), `agent_core/connectors/*` (8), `agent_core/skills/*` (5), `contact_policy.py:656`, `capture.py:249`, `storage.py:154,157`. That is the **Mouth**'s tool-result contract, consumed by the model, and `main.py` never calls into it. **The vocabulary this system gives its language model is more disciplined than the one it gives its own UI.**

**Status codes for one condition.** Signature rejection is 401 for payments (`main.py:833,868`) and 403 for Twilio and WhatsApp (`:3489,3556,3578,3620,3687,4612`) — same failure, two axes. (= M6.)

**Checked and cleared — the 200-with-error-body anti-pattern.** I asked the analyst to hunt for this as the likely headline; at the HTTP layer it is **not there**. `main.py` has zero returned `{"ok": False}`/`{"success": false}` bodies. The one `"ok": False` literal (`:773`) is immediately converted by `raise HTTPException(503, detail=result)` at `:777` — fail-closed, correctly. The single genuine instance is the WhatsApp webhook returning 200 with per-item errors inside (`db.py:10886-10974` → `main.py:4618`), already filed as H5 in `14-error-handling.md`. The hypothesis was wrong and the codebase is better than it assumed.

**Two P0-shaped gaps remain.** The SSE copilot stream (`main.py:1374-1400`) has an in-band `{"type":"error"}` convention in `copilot.py:76` that is consumed pre-stream and never reaches the wire, while `_maybe_polish()` (`copilot.py:79`) runs unguarded inside a generator whose 200 is already committed — and `Habibi/src/api/floor.ts:230-276` has handlers for `pack`, `token` and `done` and none for `error`. A mid-stream failure collapses to one fixed string. And `apiEventStream` (`config.ts:278-317`) has no `onError` parameter, so the next SSE consumer starts with none of the `.catch()` handling `floor.ts` hand-rolled.

**Proposed canonical envelope** — a superset of what already dominates, not a new shape:

```json
{ "detail": "<string, always>", "code": "<short_snake_case, optional>", "meta": { } }
```

`detail` stays a string at all 199 sites; the three dict sites move their payload to `meta` and keep the human string their exceptions already build. `code` formalizes the naming convention `bot_tools.py` has already proven works — and roughly 180 of the existing literal `detail` strings (`"pay_link_not_found"`, `"admin_required"`, `"invalid_twilio_signature"`) *are already codes* and need only be moved. `errorDetail()` gains one branch and every existing `toast.error(err.message)` keeps working.

---

## 10. The frontend consumer layer

**43 consumer modules; 42 go through `config.ts`.** The forty-third, `agent-card.ts`, makes no calls — it is the hand-written type mirror. One shared `ApiError` with `status`, one `errorDetail()`, one `retryUnlessClientError()` that correctly treats 408/429 as retryable inside the 4xx range. `API_BASE_URL` hard-fails a production build if unset (`config.ts:26-36`). This is a well-built client layer and the report should say so plainly.

**Exactly one bypass in 474 files:** `Habibi/src/routes/sandbox.lazy.tsx:432` — a raw `fetch()` for call-report export, with no auth headers, no `credentials: "include"` and no `ApiError`. The path and method are correct, so it is an error-contract hole rather than a 404.

**No dead calls.** All ~230 call sites resolve to a real route with a matching method. For a hand-maintained client against 314 routes, that is the audit's most surprising negative result.

**No codegen, anywhere.** No `openapi`/`orval`/`swagger`/`zodios` in `package.json` or `src`; no generated directory. Every type is hand-written and kept true by discipline — and the files say so themselves (`agent-card.ts:6-8` "a hand-written reflection of it"; `contact-policy.ts:16` "Mirrors backend/schemas.py :: ContactPolicyResponse"). The `minimumDue`/`lastContact` divergence in §4 is exactly what this architecture invites.

**Pagination is not a system.** Almost every list endpoint (`/customers`, `/calls`, `/disputes`, `/callbacks`, `/consent`, `/staff`, `/teams`, `/promises`, `/payment-plans`, `/redaction-records`, `/routing-rules`, `/webhook-endpoints`, `/violations`, `/scorecards`) is called with no pagination params at all — the full collection, every time. Three ad-hoc `limit=` callers exist (`agent-studio.ts:1030,1095`, `prompt-studio.ts:396`). No `offset`, `cursor` or `page` appears anywhere in the client. The backend bounds these server-side, so this is a scaling matter rather than a correctness one — but it means the pagination contract is entirely one-sided: the server has one and no caller uses it.

**Orphan routes** worth noting as unfinished wiring rather than dead code: `POST /agent-studio/skills/{skill_id}/attach` and `/detach` (`main.py:2285,2296`) — the **Skill Pack** attach path has no UI caller at all; `GET /twins` (`:901`); `GET /routing-rules/{rule_id}/executions` (`:1903`); `POST /kb/snapshots` (`:4552`); `POST /compliance/rescan` (`:1720`). The webhook receivers, Twilio callbacks and `/pay/{token}` pages are correctly not SPA-called.

---

## 11. Canonical contract candidates

Chosen on the same criterion `09-canonical-implementations.md` used: not newest, not most-imported — **the declaration that the enforcing layer already agrees with.** For a wire vocabulary, that is the SQL CHECK constraint, because it is what actually decides which values can exist. This is `test_inbox_channel_contract.py`'s reasoning, generalized.

| Concept | Competing declarations | Canonical | Why |
|---|---|---|---|
| **requestedVia** | `schemas.py:136` (Channel), `:1082` (3), `:1136` (7) | **`:1136`** | The only one matching `sql/17_phase4.sql:25-30`. Then fix `db.py:1455` to return the column |
| **reminderStatus** | `schemas.py:111` (4), `:583` (3), `:877` (6) | **`:877`** | Matches `sql/05_collections.sql:24` exactly |
| **Dispute shape** | `DisputeResponse` `:119`, `DisputeListResponse` `:636` | **`:636`** | Closed Literals where the sibling has free strings; Customer 360 becomes a projection |
| **Consent channel state** | `optedIn: bool` `:56`, `status: Literal[4]` `:1191` | **`:1191`** | A bool cannot express four states; the code already documents the ambiguity at `:1157-1158` |
| **Error envelope** | 196 string `detail`, 3 dict, 1 FastAPI 422 array | **string `detail` + optional `code`** | §9 — a superset of the 98.5% case |
| **Cross-language vocabulary parity** | `test_agent_card_schema_drift.py` (1 model), `test_inbox_channel_contract.py` (1 column) | **both mechanisms, generalized** | §1 — each already closes one leg of the triangle |

**Do not merge.** `Channel` (`schemas.py:28` — how we spoke to someone) and `RequestedVia` (how a document came to be requested) are different questions that collided on one field name. Collapsing them is what produced §2. The fix separates them; it does not unify them. The same applies to the four meanings of **Offer** and three of **Handoff** catalogued in `09-canonical-implementations.md`.

---

## 12. What to do

Ordered by (harm × how cheaply the repo can already do it).

1. **Return the column.** `db.py:1455` → `"requestedVia": _doc_requested_via(...)`, retype `DocumentRequestResponse.requestedVia` to the 7-value alias, widen `schemas.py:1082`. One line, one type alias, and Customer 360 stops lying about who asked for a document. (§2)
2. **Decide whether tenancy is a request concept.** If it is not — and `tenant_context.py` says it is not yet — `GET /billing` and `GET /billing/export.csv` must take the tenant from context, not from `Query("all")`. If it is, that is a system-wide change and this route should not be the only one that made it. (§3)
3. **Close the triangle with the tests that already exist.** One `test_wire_vocabulary_parity.py` driven by a registry of `(sql CHECK, schemas.py Literal, TS as-const)` triples, reusing `test_inbox_channel_contract.py`'s constraint reader and `test_agent_card_schema_drift.py`'s `as const` regex. Seed it with `requestedVia`, `reminderStatus`, `DisputeSla`/`WorkItemSla`, `Channel`, and the consent statuses. Both halves are already written; what is missing is the registry.
4. **Un-filter the gate that exists.** `backend-pytest.yml` is `paths:`-filtered to `backend/**`, so editing `Habibi/src/api/agent-card.ts` skips the drift test that guards it. Add `Habibi/src/api/**` to that workflow's trigger. One line.
5. **Type the 33 dict bodies**, starting with `/vault/refs`, `/vault/refs/{id}/rotate`, `/mcp/keys`, `/roles/{id}/permissions`, `/platform/switches/{key}`. `schemas.py` already has 247 models and the house style for writing them. (§8)
6. **Pick one code for one failure.** Required-field-missing is 400 or 422 depending on file region; `ValueError` is 409 through `_handle_write` and 400 inline; signature rejection is 401 or 403 by provider. Choose, then make `_handle_write` the only translator. (§8, §9)
7. **Add `code` to the error envelope** and one branch in `errorDetail()`; wire `PublishDialog` to the publish path's `CompileReport` so the **Gate** report reaches the operator. (§9, Trace 2)
8. **Bound `DisputeCreateRequest.amount`** and type `PaymentPlanCreateRequest.installments`. (§8)
9. **Give `response_model` to the 7 DELETE routes and settle on 204**, and move `Customer` out of `customer360-seed.ts` into `api/customers.ts` with the nullability the backend actually declares. (§6, §4)

Items 3 and 4 are the ones that matter beyond this audit. Everything above them is a defect; those two are the reason the next one will be found by CI instead of by a report.

---

## Findings index

**P0**
- `requestedVia` fabricated as `"voice"` on three routes; column selected and discarded — `db.py:1441,1455`; `schemas.py:136,1082,1136`; `main.py:1639,1679`; `sql/17_phase4.sql:25-30` (§2)
- `GET /billing`, `GET /billing/export.csv` take `tenantId` from the client, existence-checked only — `main.py:1018,1070`; `db.py:16782-16788`. IDOR-shaped; inert while one tenant is seeded (§3)
- SSE copilot stream has no reachable error event and no frontend `error` handler — `main.py:1382-1384`; `copilot.py:76,79`; `floor.ts:230-276` (§9)

**P1**
- Three-way `reminderStatus` Literal drift, mirrored into the frontend — `schemas.py:111,583,877`; `customer360-seed.ts:60`; `promises-seed.ts:13` (§7)
- 33 of 152 mutating routes take `dict[str, Any]`, including vault, MCP keys, RBAC and feature flags — `main.py:2464,2476,2490,2857,3835` + 28 others (§8)
- 178 of 314 routes carry no `response_model`; the backing `db.py` functions are `dict[str, Any]` too (§5)
- `Customer.minimumDue`/`lastContact` non-nullable in TS, nullable in Python; the live type lives in the mock file — `schemas.py:158-159`; `customer360-seed.ts:135-136`; `api/customers.ts:14` (§4)
- Same-class validation failure returns 400 or 422 by file region; `ValueError` returns 409 or 400 by call style — `main.py:732` vs `:837,4463`; `:2167` vs `:4892` (§8)
- `detail` is a string at 196/199 sites and a dict at 3; FastAPI's 422 is a third shape — `main.py:777,3128,3130` (§9)
- The only structured, `code`-bearing error shape is discarded at `errorDetail()` and never reaches the component that can render it — `config.ts:89-112`; `PublishDialog.tsx:100` (§4, §9)
- Dispute, Consent and Document DTO drift between embedded and standalone shapes — `schemas.py:56/1191`, `119/636`, `133/1116` (§7)
- `DisputeCreateRequest.amount` unbounded; `installments` untyped — `schemas.py:888,897` (§8)
- DELETE has four response shapes across seven routes (§6)
- `/calls` vs `/interactions`; four lexemes for "webhook" (§6)
- Two unreconciled authorization systems (main API vs MCP HTTP) (§6)
- Raw `fetch()` bypassing auth headers and `ApiError` — `sandbox.lazy.tsx:432` (§10)
- No codegen; every frontend type hand-written and free to drift (§10)

**P2**
- No API versioning, no `deprecated=`, no `Deprecation`/`Sunset`; `version="0.1.0"` never moved and is not served in prod (§5)
- 0 `tags`/`summary`/`operation_id` on 314 routes (§5)
- 61 of 247 models omit `extra="forbid"`, correlating with age (§7)
- 13 required-but-nullable fields, 5 on `BotDeploymentResponse` (§7)
- snake_case `AgentCard` embedded untyped in a camelCase response; `main.py:2050` tolerates both keys (§7)
- No route returns 201 (§6)
- `GET /mcp/tasks` `status` unconstrained; KB content-type unvalidated; `chunkSize`/`overlap` unbounded (§8)
- FastAPI's 422 array is never parsed for field-level errors (§8)
- `apiEventStream` has no `onError` parameter (§9)
- Raw MinIO SDK text in a client-visible `detail` — `storage.py:252` → `main.py:4460,4482` (= M1)
- No pagination convention on the client; no `offset`/`cursor`/`page` anywhere in `Habibi/src` (§10)
- Orphan routes: skills attach/detach, `GET /twins`, routing-rule executions, `POST /kb/snapshots`, `/compliance/rescan` (§10)
- `/readyz` auth exemption for a route that does not exist — `mcp_http/http_app.py:22` (§6)

**Checked and cleared** — hypotheses tested and found unfounded, recorded so the next audit does not re-spend the effort: path shadowing (0 of 314); duplicate `(method, path)` pairs (0); dead frontend calls (0 of ~230); Pydantic v1/v2 mixing (0); raw ORM row leakage into responses; unbounded `limit`/`offset` (bounded everywhere but one status filter); 200-with-error-body at the HTTP layer (1 instance, already filed as H5); frontend validation stricter than backend (no frontend validation to speak of); duplicated TS DTOs for Customer/Offer/Call/Promise (one canonical each); trailing-slash and path-casing inconsistency (none).
