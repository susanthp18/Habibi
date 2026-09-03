# 18 — Application security architecture

**Scope:** `backend/` HTTP, workers, voice; `Habibi/src` operator UI. `PRAXIST-main/` excluded (vendored; not in the backend image).
**Date:** 2026-09-02
**Mode:** Read-only. No application file was modified, no scanner was installed, no request was sent at a live target.
**Method:** six parallel analysts — static, authentication, authorization, injection, secrets, dependency-security — plus a parent re-read of every headline claim against source. Claims that did not survive that second pass were dropped or recast. Companion reports [19-auth-authz.md](./19-auth-authz.md), [20-config-secrets.md](./20-config-secrets.md), and [21-dependency-supply-chain.md](./21-dependency-supply-chain.md) were treated as hypotheses, not as evidence.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Deployment, Tool Grant, Offer, Gate, Flow, Handoff, Reachability, Mission, Cadence, Outcome. The Inbox flag `contactableNow` is the **contact Gate**, not Agent Card Reachability.

---

## The measurement caveat

No Bandit, Semgrep, pip-audit, or Trivy is installed on this machine, and none runs in CI (that absence is finding **X11**). `npm audit` was run read-only against Habibi. Python CVEs were assessed from manifests and, where the local `.venv` actually contained the package, from installed metadata. **No finding below is a scanner hit without a source→sink read.**

Three rules:

1. **A fail-open control that is documented as non-prod is still a finding when the shipped `.env` is `APP_ENV=dev` and the API is on a public URL.** That is the live deploy, not a hypothetical.
2. **Bound SQLAlchemy parameters are not SQL injection.** Dynamic `SET` clauses that interpolate **allowlisted column names** with bound values are not injection. Identifier interpolation from an allowlist (`_CUSTOMER_SCOPED_TABLES`) is noted, not raised.
3. **A CVE in a package that this process never imports is not a P0.** Voice-image transitives (`nltk` via `pipecat-ai`) are ranked on the voice path only, and only when the data flow is real.

Nothing below is labelled exploitable from a live packet capture. Exploitability is “can a caller who can reach this process cause this, given the code and the shipped config shape.” Secret **values** are never quoted. Names and emptiness only.

---

## Verdict

**The interior controls are unusually good. The envelope they sit in is open.**

This system has a single reviewable permission registry with a CI totality proof, fail-closed grant lookup on database errors, HMAC-verified WhatsApp and payment webhooks, HTTPS+private-IP checks on outbound webhooks, HTML/TwiML/SSML escaping, upload caps, path sanitisation, no `pickle` / `yaml.load` / `eval` / `shell=True` production sinks, and almost no XSS surface in the operator UI.

What is wrong is not that those controls are missing. It is that **every fail-closed switch is keyed to `APP_ENV ∈ {"prod", "production"}`**, the shipped `backend/.env` sets `APP_ENV=dev` with empty `API_KEY` / `API_KEY_MAP`, and several behaviour flags (`BILLING_ENV`, `BOT_ENVIRONMENT`, `TREATMENT_MODE`) already say production. Authentication off also turns authorization off (`authz.enforcement_enabled` follows whether keys exist). Object visibility follows both.

So today, a caller who learns the tunnel URL does not need to beat the registry, the HMAC, or the SSRF resolver. Those fire after a gate that is not shut.

Two findings are independent of that envelope and would still hurt a correctly locked production:

- **X3** — emptying a role’s grants restores `ROLE_DEFAULTS`. The Roles screen then shows `[]` while the resolver hands the role its full default Tool Grant.
- **X7** — a cardless Mouth (`ToolState.allowed is None`) is fail-open. ADR-0002 (“cardless agents are denied every tool”) is accepted and **not implemented**. Prompt injection can drive live CRM tools, including from the sandbox when a real `customerId` is pinned.

Classic injection (SQL, command, SSTI, stored XSS) was **not** confirmed on attacker-reachable paths.

---

## Attack surface map

```
Browser (VITE_API_KEY + VITE_ACTOR_USER_ID, baked at build)
  → CORS (allowlist or localhost regex, credentials=true)
  → ApiKeyMiddleware (skipped if keys empty; OPTIONS always skipped)
  → _authz_guard (skipped if enforcement off; WS skipped always)
  → handler
       ├─ visibility.predicate   (few list reads)
       ├─ _assert_tenant_owns    (some by-id writes)
       └─ RLS                    (inert)

Public / signature paths (no API key):
  /health /ready
  WhatsApp HMAC          fail-closed
  Twilio voice callbacks fail-open outside prod
  /pay/{token}           capability URL
  payment HMAC           fail-closed
  /ws                    VOICE_WS_PROXY_SECRET, fail-open outside prod
  POST /a2a              mTLS headers, no API key
```

| Layer | Control | Shipped posture |
|---|---|---|
| Transport | TLS at tunnel / reverse proxy; no `verify=False` in app code | App itself sets **no** HSTS / CSP / frame-ancestors |
| Authentication | Static `X-API-Key` / Bearer. No session, JWT, cookie, or OIDC | Keys **empty** → auth off |
| Actor | `API_KEY_MAP` or shared key + `X-Actor-User-Id` | Header honoured whenever not prod |
| Route authz | `ROUTE_PERMISSIONS` + `PUBLIC_ROUTES`; CI `assert_registry_covers` | Off when keys empty |
| Object visibility | Constant SQL predicate via `/*VISIBILITY*/` | ~14 list sites; conversations unscoped |
| Tenant / RLS | `rls.py` designed; boot never enables | Deferred; listed in `_DEFERRED_HARDENING_CONTROLS` |
| Webhooks in | WhatsApp / payments HMAC fail-closed; Twilio optional off-prod | Dual exempt-list mismatch on two routes |
| Webhooks out | HTTPS, send-time DNS public check, no redirects, HMAC | DNS then reconnect (rebinding TOCTOU) |
| Mouth tools | Tool Grant from Agent Card; Locked Engines at publish | Cardless = `allowed=None` = no filter |
| Frontend | No route guards, no roles on `/me` | Cannot weaken backend; cannot hide surfaces |

`main.py` never calls `load_env()`. `_IS_PROD` is assigned at import (`main.py:204-205`) from the **process** environment. Compose `env_file` injects before Python starts, so containers see `.env`. A documented bare `uvicorn` start does not: `APP_ENV=production` sitting only in `.env` is invisible to those gates (report 20 C4, re-confirmed).

---

## Confirmed findings

Ranked by exploitability today × impact. **LIVE** means the shipped non-prod envelope makes it reachable now. **WHEN AUTHZ ON** means it survives locking the envelope.

### P0

#### X1 — Authentication and authorization fail open together

**LIVE.** `main.py:291-294`, `authz.py:624-639`, `actor_context.py` no-key path.

Empty `API_KEY` / `API_KEY_MAP` ⇒ `auth_required=False` ⇒ middleware still binds an actor (header or default admin `priya-nair`) ⇒ `enforcement_enabled()` is false. One missing credential disables both layers. `APP_ENV=dev` also skips the production boot refusal (`main.py:431-438`).

**Impact:** Unauthenticated read/write of a regulated collections CRM on any host that can reach the process, with writes attributed as a chosen or default staff user.

**Why it is one finding, not two:** There is no defence in depth between authn and authz. Fixing only `APP_ENV` without requiring keys, or only keys without failing closed when they are absent, leaves the other door.

#### X2 — Voice Media Streams WebSocket upgrades without the proxy secret

**LIVE.** `main.py:3442-3479`, `/ws` in `_AUTH_EXEMPT_PREFIXES` (`:250`).

`_voice_ws_upgrade_authorized` compares path/header/query to `VOICE_WS_PROXY_SECRET` with `secrets.compare_digest`. If that fails and `_IS_PROD` is false, it **`return True`**. The secret can be configured and still unused. Twilio’s signature is not on the WS upgrade; the comment at `:3461-3470` states that correctly — then the non-prod branch ignores it.

**Impact:** Anyone who can open `wss://{public-host}/ws` joins the media-stream proxy: live call audio, injection into the voice runner.

#### X3 — Revoking every permission from a role restores `ROLE_DEFAULTS`

**WHEN AUTHZ ON** (UI lying is always live). `authz.py:702-709`; write `db.replace_role_permissions` (`db.py:473-508`); Roles UI `Habibi/src/routes/roles.tsx`.

A `LEFT JOIN` on a role with zero `role_permissions` rows yields `explicit == set()`. The resolver treats that as “never configured” and unions `ROLE_DEFAULTS`. `GET /roles` still returns `[]`. Admin is additionally un-revocable (`authz.py:713-714` name short-circuit; `db.py:494-495` re-appends `ADMIN_WRITE`).

`test_explicit_grant_beats_default_so_revocation_works` covers **partial** revoke only.

**Impact:** The one operator action that should strip a role does the opposite. Incident response that “locks down Agent” hands Agent its full default grant, including voice operate where that is defaulted.

---

### P1

#### X4 — Shared key (or auth off) + `X-Actor-User-Id` is full identity assume

**LIVE** in non-prod. `actor_context.py:58-65`, `:221-226`. Default `ALLOW_ACTOR_HEADER` is on whenever not prod. `GET /staff` enumerates ids. Seeded admin id is public in this repo.

**Impact:** Privilege assumption as any staff user, including the default admin.

#### X5 — Twilio callbacks accept a missing signature outside prod

**LIVE.** `main.py:3387-3396`. Token may be set; missing `X-Twilio-Signature` still returns `True` when not `_IS_PROD`. Paths `/twilio/voice/incoming|fallback|stream-status|call-status` are API-key exempt.

**Impact:** Forged call/SMS status into the attempt ledger and treatment inputs. WhatsApp and payment HMACs do **not** have this hole — do not generalise “webhooks are fail-closed” to Twilio.

#### X6 — `POST /a2a` skips both API-key and authz; trusts client SSL headers

**LIVE if the app port is reachable without an ingress that strips `X-SSL-Client-*`.** `main.py:278-279`, `PUBLIC_ROUTES`, `agent_core/a2a.py:23-69`.

Bearer without a “verified” cert is correctly refused (`a2a_mtls_required`). The verify signal is a **request header**. No compose/ingress config in this repo strips or overwrites those headers. Direct-to-uvicorn, the check is spoofable. Partner match still needs a known DN/fingerprint in `a2a_partners`.

**Impact:** A2A partner impersonation if a row exists and the process is exposed. Ranked P1, not P0, because it needs a partner row and a2a enabled.

#### X7 — Cardless Tool Grant is fail-open (ADR-0002 unimplemented)

**LIVE** on any Mouth without a parseable authored Agent Card. `agent_core/skills/runtime.py:182-185`, `:127-145`; `bot_tools.execute_tool:831` (`if ctx.allowed_tools is not None`); `bot_runtime.py:947-950` falls back to `TOOL_DEFINITIONS`; sandbox copies the same sentinel (`sandbox_runtime.py:232-244`).

`ToolState.has_grant` documents the ticket: `None` means “no card, so no grant” and **every caller still reads that as no filtering**. An authored card **does** set `allowed` and refuse unknown tools.

**Impact:** Prompt injection (borrower text, WhatsApp, sandbox utterance) can invoke live CRM handlers — PTP, notes, goodwill request — without a Tool Grant. Locked Engines still cap **waiver amounts** when `evaluate_authority` runs (`AUTHORITY_MODE=live` + matrix). Treatment **dials** are not mouth tools (`treatment/enact.py` is mode-gated). The hole is “run the catalog,” not “invent a higher waiver cap.”

#### X8 — Conversations, exports, and several by-id reads ignore visibility (and often tenant)

**WHEN AUTHZ ON** within the single seeded tenant; cross-tenant **LATENT**. `db._conversation_base_rows` (`db.py:8994-9056`) filters `cv.id` / `updated_after` only — no `c.tenant_id`, no `/*VISIBILITY*/`. `GET /interactions/{id}/export` (`voice/call_export.py:50-61`) is existence-only. Prompt versions / deployments by id have no tenant predicate (`db.py:12913-12932`). Writes use `_assert_tenant_owns` at best — not assignee scope (`visibility.py:42-49`).

Handoff **claim** is the exception: tenant + already-claimed-by-other (`db.py:4576,4598-4599`).

**Impact:** Any actor with `INTERACTIONS_READ` sees the whole inbox and can export the richest PII bundle by id. Agents see each other’s books on the primary screen.

#### X9 — Outbound SSRF: DNS check then reconnect without IP pinning

**Amplified LIVE when X1 holds** (unauthenticated webhook/connector create); otherwise needs `INTEGRATIONS_WRITE`. `webhooks_dispatch.resolve_public_host` (`:132-157`) then `_post` uses the hostname again (`:171-173`). Connectors reuse the same helper (`connectors/persist.py:29-60`) and `httpx.post` the URL (`:361-374`). Registration (`ops_screens._validate_webhook_url:51-80`) correctly refuses to resolve at request time.

Mitigations that hold: HTTPS-only, private/link-local/reserved rejection, `follow_redirects=False` on the webhook client, vault bearer not sent unsigned, tests in `test_webhooks_dispatch.py` / `test_connector_ssrf_guard.py`.

**Why still a finding:** Classic DNS rebinding TOCTOU. The comment at `ops_screens.py:73-77` says the worker must pin; it never did.

#### X10 — Operator UI can bake the CRM key into JavaScript

**Structural; live if `VITE_API_KEY` is set at build.** `Habibi/src/api/config.ts:38-54`. Production build already refuses mock mode and a missing API base URL. There is no cookie session. `credentials: "include"` is preparatory.

**Impact:** Every browser that loads the UI holds the shared key. XSS, if introduced later, becomes full API compromise. Treat `VITE_*` secrets as public.

#### X11 — No dependency-vulnerability gate, and no Python lockfile

**Hygiene that makes every future CVE silent.** CI: `npm ci` / `pip install`, no `npm audit`, no `pip-audit`, no OSV-Scanner, no Dependabot. `backend/requirements*.txt` have no hash pin. `Habibi/bunfig.toml` `minimumReleaseAge` is the only supply-chain control and CI uses **npm**, which ignores it.

Voice transitives: `pipecat-ai==1.6.0` pulls `nltk` (download/SSRF advisories in 3.10.0; first-party code does not import nltk — this is a **voice image** concern) and `aiohttp` (client parser DoS, GHSA-cq5v-8q36-5273, fix 3.14.3). This session’s CRM `.venv` did not contain `nltk`; do not claim it is loaded in the API process.

Starlette 1.3.1 / FastAPI 0.139.2: form-parsing CVE **already patched**. `request.form()` is used on Twilio inbound (`main.py:3487+`) — that path would have been P1 if unpatched.

npm advisories (brace-expansion, browserslist, js-yaml, nanoid, postcss) are **dev/build**. Habibi has no markdown→HTML stack.

#### X12 — Sandbox tool loop writes the live ledger

**LIVE for an authenticated operator** (or anyone, under X1). `sandbox_runtime.py:317-321` and the `execute_tool` loop (`:292-296`). Pinning a real `customerId` with tools enabled runs the same handlers as production. No shadow ledger.

**Impact:** Rehearsal that creates a real PTP / goodwill path on a borrower. Audit rows detect; they do not prevent.

---

### P2

#### X13 — No HTTP security headers in the API or Habibi SSR

Middleware stack is GZip, ApiKey, Metrics, RequestId, CORS (`main.py:607-665`). Habibi server sets content-type. Missing: CSP, HSTS, `X-Frame-Options` / `frame-ancestors`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`. May exist at a proxy **not in this repo**.

#### X14 — `/ready` echoes MinIO exceptions; DB readiness deliberately does not

`storage.ping` (`storage.py:145-157`) → `detail: str(exc)` → `main.py:759-777`. Contrast `db.py:344-353` (`detail: "db_unavailable"`). Unauthenticated. Topology / credential-shape leak.

#### X15 — Interaction and billing exports lack `Cache-Control: private, no-store`

`main.py:1030-1081`. TTS preview sets `private, max-age=3600` (`:3042-3047`). Shared-browser / proxy cache of transcripts and tool args.

#### X16 — `GET /pay/{token}` does not enforce `expires_at`

`main.py:781-792` → `payments.load_intent_by_token` (`:397-412`) has no expiry predicate. `record_payment` **does** expire (`:154-162`). Render treats `status == "expired"` (`:442-443`) but nothing on GET flips that from the timestamp. Public, unrate-limited, PII (name, amount, account tail). GET also `mark_opened` (state-changing GET — P3 sibling).

#### X17 — Dual exempt lists: HMAC routes that 401 before HMAC once keys exist

`PUBLIC_ROUTES` includes `POST /twilio/sms/status` and `POST /webhooks/collections/payment-events` (`authz.py:229,233`). `_AUTH_EXEMPT_PREFIXES` does not (`main.py:233-257`). **Availability, not bypass:** once `API_KEY` is set, Twilio SMS receipts and CBS bounce ingest 401 before the signature check.

#### X18 — Outbound `X-BigBound-Event` is unsanitised

`ops_screens._ensure_event_type` (`:943-958`) inserts **any** `events[]` string; `_upsert_endpoint_children` (`:1095-1096`) does not restrict to `EVENT_CATALOG`. Delivery sets `EVENT_HEADER: str(event_name)` (`webhooks_dispatch.py:441-447`) with no CRLF strip. HMAC covers body+timestamp, not this header.

Needs an authenticated integrations writer (or X1). Custom `headers[]` are persisted without CRLF checks (`:1108-1123`) but **are not attached** on the live POST — latent.

#### X19 — WhatsApp verify GET uses `==`; POST HMAC is constant-time

`main.py:4595` vs `whatsapp.py:48-65`. Timing oracle on `WHATSAPP_VERIFY_TOKEN`. API keys, payment HMAC, voice WS compare, MCP keys use `compare_digest`.

#### X20 — Log redaction is borrower-PII-in-`message` only; CRM facts leave in LLM prompts

`pii_redact.py` + `observability.py:344-377`: no credential detectors; `extra` and tracebacks unredacted. `voice/persist.py` masks `\d{7,}` after `redact_text`; logs/Sentry do not. Azure chat/embed logs token counts (good); system/user content still carries name, outstanding, DPD, product, account tail to the model provider. Intentional product behaviour, still a handling boundary.

#### X21 — Permission cache is not busted on grant write

`invalidate_permission_cache` is not called from `replace_role_permissions`. Up to 30s (and forever in other processes) of stale grants. Consistency finding that is also an authz lag. See report 17 S2.

---

### P3 (kept short)

| ID | Title | Notes |
|---|---|---|
| X22 | Unbounded request strings | Uploads capped (`main.py:207-221`); many `str` fields have no `max_length` |
| X23 | Hosted-pay GET marks `opened` | Prefetch / scanners; complete is POST + sandbox-gated |
| X24 | Voice WS length short-circuit | `main.py:3414-3417` leaks secret length before `compare_digest` |
| X25 | npm build-toolchain advisories | Not on borrower XSS path; still ungated (X11) |
| X26 | Weak compose DB / MinIO defaults | `collections`/`minioadmin` in templates; loopback-gated for MinIO fallback |

---

## Rejected false positives

| Hit | Why it is not a finding |
|---|---|
| Hundreds of `text("""… :param """)` | Bound parameters |
| `text(f"UPDATE promises SET {updates}")` and siblings | Column fragments from **fixed maps**; values bound |
| `_assert_tenant_owns` `FROM {table}` | `table ∈ _CUSTOMER_SCOPED_TABLES` |
| Dashboard interval f-strings | Days from `_DASHBOARD_RANGE_DAYS` |
| KB/TTS `WHERE {where}` | Fixed fragments + bound `:q` |
| `SET LOCAL app.tenant_id` | `tenant_context.validate` charset |
| `visibility.predicate(alias)` | `alias.isidentifier()` |
| `prompt_render` | Whitelist `{var}`; not Jinja |
| Skill `run_script` | Allowlisted pure functions; no subprocess |
| `subprocess` | Tests and operator scripts; no `shell=True` in app |
| `pickle` / `yaml.load` / `eval` / `verify=False` | **No app matches** |
| Habibi `dangerouslySetInnerHTML` | Compile-time `THEME_INIT`; chart CSS variables — not user HTML |
| Inbox `{message.text}` | React text (escaped) |
| Pay page HTML | `html.escape` on every dynamic field |
| SSML / TwiML | `xml.sax.saxutils.escape` / `quoteattr` |
| Skill zip import | Members read into memory; **no `extractall`** |
| TTS cache path | SHA-256 hex under fixed dir |
| MinIO / KB filenames | `_safe_segment` / `Path(filename).name` |
| WhatsApp Graph `urlopen` | Fixed `graph.facebook.com` + env ids, not caller URL |
| nltk JVM injection CVE | Needs Stanford wrappers; voice path is `sent_tokenize` / download |
| Starlette form CVE | Patched at 1.3.1 |
| Classic CSRF | No cookie session today. Returns if cookies are added while CORS has `allow_credentials=True` |

---

## What is already good

1. **Authz registry + CI totality** — unregistered routes denied; policy is one table (`authz.py:213-608`, `assert_registry_covers`).
2. **`_authz_guard` uses middleware actor**, not the ContextVar default (`main.py:539-542`).
3. **Grant lookup fails closed** on DB errors (`authz.py:730-735`, `:792-794`). Unknown roles get tightest visibility (`OWN`).
4. **WhatsApp POST and payment HMACs fail closed** with `compare_digest` (ASCII-safe on WhatsApp).
5. **Twilio API-key exemptions are segment-bounded** (no blanket `/twilio`) — outbound dial is not internet-open by prefix mistake.
6. **Webhook egress design is intentional and tested** — HTTPS, private-IP classes, no redirects, unsigned endpoints fail `secret_unavailable`.
7. **MCP HTTP** — hashed keys, scopes, default-deny tools, localhost bind.
8. **Pay-link entropy 192-bit**; complete path checks expiry; HTML escaped; complete disabled in production hosted mode.
9. **Uploads capped**; path traversal guarded on MinIO/KB/TTS cache; skill zip is not Zip Slip to disk.
10. **No insecure deserialization or shell-out** in the app. Eligibility DSL refuses `eval` (`capture.py` comment is a warning, not a sink).
11. **CORS is outermost** so 401s still carry ACAO (`test_auth_cors_middleware.py`).
12. **DB `/ready` will not stringify a DSN.** Voice WS URLs redacted in logs (`_redact_voice_ws_url`).
13. **Habibi production fail-closed** on mock / missing base URL. No auth secrets in `localStorage`.
14. **Prompt layout** keeps CRM fields out of frozen policy text (`prompt_render`).
15. **Authority and treatment are shadow-by-default**; live enactments check mode at the top. A Mouth cannot place a collection dial by talking.

---

## Corrections to companions

| Report | Adjustment |
|---|---|
| 19 | P0-1 (revocation restore) is **authorization**, not authentication. Authn P0s are X1+X2. “Payment and WhatsApp HMACs fail closed” must not be read as covering Twilio. `localStorage` holds many prefs, not only theme — but still **no auth secrets**. |
| 20 | Constant-time compares are **not** universal: WhatsApp **GET** verify is `==` (X19). Voice bare-digit redaction is not shared with logs (X20). LLM prompt egress of borrower facts was not a 20 finding and is X20. Unset payment/WA secrets fail closed; the “configured but unused” secret is `VOICE_WS_PROXY_SECRET` under non-prod (X2). C4 (import-time `_IS_PROD` vs `load_env`) re-confirmed: `main.py` never calls `load_env()`. |
| 21 | nltk/aiohttp are **voice-image** transitives of `pipecat-ai==1.6.0`, not CRM API imports. This session’s API `.venv` had no `nltk`. Starlette/FastAPI request-form CVE is **already fixed** while Twilio `request.form()` is live. bunfig is inert under `npm ci` — keep as hygiene, not as a working control. |

---

## If only seven things are fixed

1. **Require credentials to boot, always.** Absent `API_KEY` / `API_KEY_MAP` must be a refusal, not a mode (`main.py:292`). Do not derive `auth_required` from whether secrets happen to be set.
2. **Load `.env` before `_IS_PROD` is decided**, or stop documenting a launch path that never loads it. Setting `APP_ENV=production` in `.env` is otherwise silent on bare uvicorn.
3. **Treat unrecognised `APP_ENV` as production**, or allowlist true non-prod names in one place (`env_utils.NON_PROD_ENVS` already exists; `main.py` re-implements a deny-list of two strings).
4. **Delete the non-prod `return True` on the voice WS gate** (`main.py:3479`). If `VOICE_WS_PROXY_SECRET` is set, require it; if it is unset, refuse the upgrade.
5. **Distinguish “role has empty grants” from “role was never configured”** (`authz.py:702-709`). Empty explicit set must mean empty, not defaults. Call `invalidate_permission_cache` from `replace_role_permissions`.
6. **Cardless Mouths deny every tool** (implement ADR-0002). `ToolState.allowed is None` must not skip `execute_tool`. Sandbox with a real customer must not share the live ledger.
7. **Scope conversations and interaction export** the way `GET /customers` is scoped (`/*VISIBILITY*/` + tenant). Pin webhook/connector connects to the resolved public IP.

Four of those are one-line or one-function. None needs a shadow period. X8 and X9 are the first that need tests more than a line.

---

## Unverified / out of scope this pass

- Live packet to the tunnel, ingress mTLS stripping for `/a2a`, and whether `PUBLIC_BASE_URL` still points at a working ngrok host **right now**.
- Container OS layers (no image scan).
- Whether a reverse proxy already injects security headers.
- PRAXIST-main (vendored; not in `backend/` Docker context).
- Runtime confirmation that `nltk.download` fires on the voice container’s boot — ranked from Pipecat’s import graph and OSV, not from a process trace in this session.
