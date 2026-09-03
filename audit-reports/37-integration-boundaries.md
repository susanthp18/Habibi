# 37 — Integration boundaries

**Role:** Enterprise integration architect.
**Question:** Every hop that leaves this process — who owns it, what does it promise, and what happens when it fails?
**Scope:** `backend/` (FastAPI API, two job workers, two voice runners, SQL, Alembic). `Habibi/` only where it originates an external call. `PRAXIST-main/` is out of scope — it is a separate vendored project of 4,518 files with no import edge into `backend/`.
**Date:** 2026-09-03
**Mode:** Read-only. No installs, no builds, no containers started, no tests, no migrations, no database or provider connection. The only files written are this report and its scratch drafts.

**Supersedes an earlier run.** A previous `37-integration-boundaries.md` (380 lines, 31,234 bytes) existed at this path when this audit began. It is a competent report and this one is built on top of it rather than around it — I preserved a verbatim copy before writing, and §4 records what happened to each of its load-bearing claims. Two things justify a second pass. First, that run states plainly that **its database and file/storage analysts aborted on a usage limit** and those two families were written up by hand from the same files; both families were re-run here with full analyst budgets. Second, an independent verification pass over a prior audit is worth more than a third opinion assembled from scratch — where we agree, the claim is now checked twice by different methods, and where we disagree, §4 says which reading survived contact with the source.

**Relationship to the rest of the series.** Report 25 asked whether a hop *survives* failure (timeouts, retries, breakers). Report 26 asked how the AI providers *couple* to the domain. Report 20 inventoried the config keys. Report 24 asked what is *visible*. This report asks a narrower question than any of them: **who owns the hop** — and it treats a second client for the same vendor as the defect, regardless of whether either client is individually well built.

**Method.** Five parallel analysts — HTTP, database, AI provider, queue/cache, file/storage — each briefed with first-hand ground truth I established before spawning them, and each given three calibrations drawn from errors I had already made in this series: read the docstring before calling anything duplication (this codebase documents its own trade-offs honestly and at length); `httpx`'s default timeout is 5.0s, not infinite, so a missing `timeout=` is a wrong value rather than an unbounded hang; and read the whole call before concluding, because a three-line grep window hides the argument on line four. Every claim this report headlines was then re-read from source by me. Numbers carry the method that produced them. Where an analyst and I disagreed, both readings are stated.

---
## Verdict

**This codebase knows how to build an integration boundary. It has built nine or ten of them properly, and it applies each one to exactly the scope its author was looking at.**

That is not a figure of speech. In twelve separate places, the correct mechanism exists, is well built, is usually documented with the incident that motivated it — and stops at a boundary that has a neighbour on the other side:

| The mechanism | Where it works | Where it stops |
|---|---|---|
| The LLM gateway | wraps `azure_openai.chat_with_tools` | the voice runtime has its own Azure client; 2 of 4 profiles are unreachable (**I1**) |
| `env_utils.env_name()` | `sign.py`, `vault/seal.py`, pinned by a test | the test scans `agent_core/` only; `main.py` has its own copy and gates webhook auth on it (**I2**) |
| The auth-exempt list | four `/twilio/voice/*` callbacks | `/twilio/sms/status` and the bounce webhook 401 before their signature check runs (**I5**) |
| `resolve_public_host` | validates every DNS answer, 13 tests | the resolved address is discarded and httpx re-resolves (**I6**) |
| `rls.py` — 633 lines, correct, self-protecting | complete and tested | never invoked; the app connects as the BYPASSRLS role the module refuses to run as (**I10**) |
| `ensure_bucket()` | provisions `collections-kb` | code names seven buckets; recordings silently land in the KB one (**I13**) |
| `transcript_view.redact_line` | the LLM prompt path | the object-store path writes transcripts verbatim (**I14**) |
| "don't publish a process-local zero" | `voice_sandbox.py`, with the reason written out | `observability.py` publishes exactly that number (**I16**) |
| `ignore_exceptions=(ValueError,)` | the MinIO breaker, with the reasoning | the WhatsApp breaker counts config errors as outages (**I17**) |
| Provider provenance | written on every bind by `provider_bind` | nothing persists `session.extra["providers"]`; it dies with the process (**I20**) |
| Fail-closed locale resolution | `factory.NoBindingError`, and the docstring naming the bug | `tuning_apply.py:70` still returns `EN_IN` for an unmapped tag (**I20**) |
| The analysis lane's isolation | `azure_openai`'s own client, timeout, semaphore, breaker | `maybe_chat` is called before all four of them (**I21**) |

Read that column twice. Every fix in this report already exists in this repository, written by someone who understood the problem. The gap is never knowledge. It is that nobody was asked "and what else touches this?"

**Five findings are worth acting on this week, and one of them is dated.**

**I22 — the Fish free-tier promotion expired on 2026-08-31. Today is 2026-09-03.** `fish_tts.py:45-60` documents the deadline, the migration (`FISH_TTS_MODEL=s2.1-pro` plus a funded balance) and a first-hand test of both model ids. Nothing has been flipped: Fish direct, the OpenRouter path, the registry row and `.env.example` all still name `s2.1-pro-free`, and a test asserts it. Because the documented Fish→OpenRouter fall-through points at *the same expired promotion*, the fallback cannot rescue the primary — the expected sequence today is 402, fall through, 402, HTTP 422.

**I5 — two signature-verified webhooks return 401 before reaching their signature check.** `authz.py:229` marks `/twilio/sms/status` public and explains that the signature *is* the authentication; `main.py:233-257` keeps a second, independent list that omits it. On any deployment with `API_KEY` set — which `main.py:432` makes mandatory in production — every Twilio SMS delivery receipt is rejected, so the fallback channel used when WhatsApp is outside its 24-hour window has no delivery evidence at all. The bounce-ingest webhook has the identical mismatch. The cause is visible in the code: a real security fix replaced a `/twilio` prefix with an explicit enumeration, and the enumeration covered the four callbacks its author was looking at.

**I13 — call recordings are written into the knowledge-base bucket.** The `recordings` bucket is never created, so every upload fails and is silently retried into `collections-kb`, sharing one access policy with policy documents. Roughly three recordings open the shared `minio` breaker, which then fails KB uploads. With **I14** — transcripts serialised to storage with no redaction, while the same text is carefully redacted twice on the way to the model — the artefact landing in that bucket is an unredacted record of what a borrower said aloud.

**I10 — row-level security is complete, correct, and switched off.** `rls.py` derives policies from the foreign-key graph, applies `FORCE ROW LEVEL SECURITY`, and refuses to run as a bypassing role. The application connects as exactly that role, no migration ever calls it, and tenant isolation rests entirely on 70 hand-written predicates in `db.py` spelled four different ways against 364 `SELECT`s. One instance of the failure it guards against has already been found and fixed by a test rather than by review.

**I1 — the LLM spend cap reroutes around itself when it engages.** A cap breach raises, the one caller catches every exception and falls through to the uncapped direct-Azure path, and the usage meter labels that fallback traffic as gateway spend. `LLM_GATEWAY_CAP_VOICE_INR` is documented in `.env.example` and can never bind, because the voice hop never reaches the gateway.

**What is genuinely good.** `azure_speech.py` is the best HTTP client in the repository and the only one that honours `Retry-After` or applies jitter. Inbound webhook verification is uniform, constant-time and fails closed everywhere. The Alembic chain is perfectly linear across 102 revisions with a single head. pgvector is correctly indexed and queried. **No session is held across an external HTTP call on the request path** — a 618-block scan found three candidates, all false positives — and the rule is written down in three places. `visibility.py` is the canonical predicate this codebase should have copied for tenancy, and explains why in its own docstring. `voice/provider_bind.py`'s two-layer bind policy is a correct, well-argued answer to a question the prior audit read as a contradiction (§4, row 1) — though the provenance guarantee that makes it safe is never written to disk (**I20**). Nothing blocks the event loop: every synchronous provider call from `voice/` goes through `asyncio.to_thread`, at 36 sites.

**One structural fact underlies half of this.** `db.py` is **18,087 lines** — 440 functions, one class, 486 `text()` calls, and about ninety function-local imports reaching `storage`, `whatsapp`, `azure_openai`, `kb_ingest` and `agent_core.*`. Those deferred imports are the diagnosis, not a style choice: a module this central cannot import its dependencies at the top because everything imports it. No integration boundary can be enforced against a file that contains the domain.

---

## 1. The surface

**Twenty-one external dependencies, reached through four different HTTP transports and three different SDK styles.** The transports are `httpx` (16 files import it, 17 client-construction sites — counted twice by different tools, ripgrep and a full `grep -r`, which agreed), `urllib.request` (one file, `whatsapp.py`), the Twilio SDK's own `TwilioHttpClient`, and the OpenAI/Azure SDK's internal client. Plus the MinIO SDK and `redis.asyncio`.

| # | Dependency | Purpose | Owning module | Second client? | Breaker | Metric |
|---|---|---|---|---|---|---|
| 1 | **Postgres 16 + pgvector** | System of record, job broker, KB vectors | `db.engine` | Alembic (`NullPool`, correct); `seed_postgres` raw psycopg | no | pool gauge |
| 2 | **Redis 7** | Voice mesh pub/sub | — | `mesh_bus` + `insurance` | no | no |
| 3 | **MinIO** | KB originals, recordings, transcripts | `storage.py` | no | `minio` | no |
| 4 | **Azure OpenAI (text)** | Chat, tools, embeddings, analysis | `azure_openai.py` | — | `azure_openai`, `azure_openai_analysis` | breaker only |
| 5 | **Azure OpenAI (voice)** | Live conversation LLM | `voice/llm_pool.py` | **separate credentials** | **no** | no |
| 6 | **LiteLLM / APIM** | Optional chat gateway | `llm_gateway/client.py` | — | **no** | no |
| 7 | **Azure Speech REST** | TTS synth, batch STT | `azure_speech.py` | `tts_catalog_sync.py` | `azure_speech` | breaker only |
| 8 | **Azure Speech (live)** | Streaming STT/TTS | `providers/factory` | — | no | no |
| 9 | **Meta WhatsApp Graph** | Outbound messages, templates | `whatsapp.py` | — | `whatsapp_meta` | queue depth |
| 10 | **Twilio Voice** | PSTN dial, redirect, conference | `voice/twilio_ops.py` | — | **no** | call_trace |
| 11 | **Twilio SMS** | PTP confirm, bounce, reminders | `twilio_sms.py` | **2nd Client** | **no** | **no** |
| 12 | **Twilio (ops script)** | Set the voice webhook | — | **3rd Client, no timeout** | no | no |
| 13 | **Fish Audio** | Preview + live TTS | `providers/fish_tts.py` | `fish_service.py` *(deliberate)* | no | no |
| 14 | **Cartesia** | Preview TTS + voice catalog | `provider_tts.py` | `provider_voice_sync.py` | no | no |
| 15 | **Deepgram** | Preview TTS + model catalog | `provider_tts.py` | `provider_voice_sync.py` | no | no |
| 16 | **ElevenLabs** | Preview TTS + voice catalog | `provider_tts.py` | `provider_voice_sync.py` | no | no |
| 17 | **OpenRouter** | Fish-via-OpenRouter preview | `providers/openrouter_tts.py` | — | no | no |
| 18 | **Tenant webhooks (out)** | Signed CRM event POST | `webhooks_dispatch.py` | — | **no** | **no** |
| 19 | **MCP remotes** | JSON-RPC tool calls | `connectors/persist.py` | — | DB-backed | health column |
| 20 | **Azure Key Vault** | Connector/provider secrets | `vault/persist.py` | — | **no** | no |
| 21 | **Inbound webhooks** | Twilio, Meta, payments | handlers in `main.py` | — | n/a | http_requests |

Read down the last two columns and the shape of this report is already visible. **Four of twenty-one outbound integrations have a circuit breaker; none has a latency or error metric.** The five named breakers — `azure_openai`, `azure_openai_analysis`, `azure_speech`, `whatsapp_meta`, `minio` — are the only outbound health signal in the system, and they are binaries that trip after a threshold rather than gauges you can watch approach one (I4).

Read down the "second client" column and the rest is visible. Twilio is reached by three independently constructed SDK clients from one credential pair. Cartesia, Deepgram and ElevenLabs each have two HTTP paths with different timeouts (60s for preview, 30s for catalog) and separately rebuilt auth headers. Azure OpenAI is reached by two clients with two credential namespaces. Azure Speech REST is reached by the shared client and by one catalog sync that bypasses it. Only one of these splits — Fish — is deliberate and documented, and it is the one that shares its timeout and payload builder.

**Nine distinct timeout values across the surface**: 1.5s (voice-runner probe), 2.5s (MCP connectors, per-row), 10s (Key Vault, both Twilio clients, outbound webhooks), 20s (LiteLLM gateway), 30s (voice LLM, provider catalog sync), 45s (Azure Speech client, STT), 60s (preview TTS, Speech catalog), 90s (Fish, OpenRouter), and unbounded (Postgres connect). Several are deliberate and argued in comments; three are accidental in the specific sense that two callers of the *same vendor* disagree. **Only two clients in the entire codebase separate connect from read** — `azure_speech.py:60` (10s connect) and `tts_catalog_sync.py:105` (15s connect). Everywhere else a single number covers DNS, TCP, TLS and the response body, so a black-holed SYN consumes the whole synthesis budget.

**Configuration surface: 242 keys** in `.env.example` — 161 live and 81 commented — across 638 lines (I8).

**Process topology.** Five containers run application code against one Postgres and one MinIO: `api`, `worker`, `bot_worker`, `voice`, `voice_insurance`. Redis reaches only three of them (`api`, `voice`, `voice_insurance`); `worker` and `bot_worker` are not given `REDIS_URL` at all. Every piece of in-process state — circuit breakers, the gateway spend cap, rate limits, caches — therefore exists in up to five independent copies. That multiplier is the quiet theme running under half the findings below.

---

## 2. What is already a real boundary

An audit that only lists defects will mislead you about this codebase. Several of these boundaries are better than what most teams ship, and three of them are the reference implementations the rest of the report measures against. Nothing below is a consolation prize — each was checked as carefully as the findings.

**`azure_speech.py` is the high-water mark and every canonical proposal in §3 is measured against it.** A module-level `httpx.Client` behind a double-checked lock (`:53-63`), `Timeout(45.0, connect=10.0)` — the only client in the codebase besides one catalog sync that separates connect from read — `Limits(max_connections=20, max_keepalive_connections=10)`, a per-request override so a caller can tighten without building a second client (`:531`, `:668`), a bounded semaphore, and a circuit breaker. Its retry is the only correct one in the repository: bounded attempts, `Retry-After` honoured with a cap, **full jitter**, and `_SpeechRetryable` (`:400-410`), which converts a retryable *response* into an *exception* specifically so the breaker can count it. That last trick is the kind of detail that only appears after someone has watched a breaker fail to open during an outage.

**Inbound webhook verification is uniform, constant-time, and fails closed.** This is the one integration concern the codebase handles the same way everywhere, which is worth noting precisely because the rest of the report is about the opposite. Meta's `X-Hub-Signature-256` is checked with `hmac.compare_digest` against the raw body, and the attacker-controlled header is ASCII-guarded before comparison (`whatsapp.py:48-67`). Twilio's `RequestValidator` is run against a reconstructed public URL that deliberately includes the query string, with a comment explaining that dropping it breaks every signature on a query-bearing callback (`main.py:3398-3408`). Payments, payment events, outbound webhook signing and the MCP HTTP server all use `compare_digest`. Every one fails closed in production. (What happens *before* the handler is I5's problem, and it is a routing bug, not a verification bug.)

**`voice/provider_bind.py` is a correct answer to a hard question, and the prior audit read it as a contradiction.** Its docstring names the incident it exists to fix — *"an operator could pick Cartesia in the Agent Studio, hear the preview, publish it, and every real call still ran Azure. A studio that configures something the runtime ignores is worse than no studio, because the screen asserts a fact about the system that is false."* It then explains why the factory raising `NoBindingError` is right in the factory and wrong at the call: *"'this tenant has not configured a provider yet' is a different fact from 'this locale is unservable', and answering it by dropping every call would make deploying the registry an outage."* Strict at the decision, lenient at the call. That is layered policy, not the inconsistency the prior audit read it as — see §4, row 1.

It belongs in this section for its policy and not for its guarantee. The docstring closes with *"every bind records what was asked for and what actually ran on `session.extra["providers"]`, so the transcript and the CRM record cannot claim a provider that never spoke"* — and that half is not implemented (**I20**). I had this module written up here as a complete positive before the provider analyst checked whether anything reads that key. Nothing does.

**`whatsapp.py`'s error classifier is vendor-specific by necessity and does the hard part.** `_classify_send_error` (`:242-280`) parses Graph's `code`/`error_subcode` and deliberately drops the raw body — which carries the recipient's number, the message text and token fragments — before anything reaches a log or a database column. It then splits `is_definite_client_error` from `is_ambiguous_transport_error`, and the queue **dead-letters the ambiguous case rather than retrying**, because Meta may already have accepted the message. That is the correct call on a channel where a retry is a second message to a borrower, and it is reasoned out in the source.

**`webhooks_dispatch.py` gets the transaction boundary right.** Events are enqueued inside the business transaction and POSTed outside it, the payload is serialised canonically (`sort_keys=True`, tight separators) so a receiver can re-sign the exact bytes, and a missing `secret_hash` refuses to send rather than delivering unsigned — *"Unsigned delivery is not a degraded mode, it is a different security posture."* At 24 tests it is the best-covered integration in the codebase.

**Two circuit breakers is the right number.** `circuit_breaker.py` is in-process and generic, with a probe-generation stamp that stops a stale half-open probe from closing the circuit on a late success. `agent_core/connectors/circuit.py` is DB-backed, per-tenant-row, and survives restart — which it must, because connectors are registered per tenant across a multi-process fleet. Both docstrings state their reasoning and `tests/test_connector_circuit.py` cross-references the other. This is a justified split, not duplication. The one real defect is that their thresholds are configured differently: `circuit_breaker` reads `CIRCUIT_FAILURE_THRESHOLD`/`CIRCUIT_RESET_TIMEOUT_S`, while `connectors/circuit.py:38-39` hardcodes `OPEN_AFTER = 3` / `COOLDOWN_S = 30`, reachable from no env var.

**`agent_core/providers/fish_tts.py` and `fish_service.py` are a documented, correctly-factored split** — the SDK-free HTTP client the API process imports for voice auditions, and the Pipecat service only the voice worker needs, sharing `_TIMEOUT` and `build_payload` so *"an audition and a call are built from identical bodies."* Two files reaching one vendor is the pattern this report treats as a defect; this is the case where it is not, and it is the control that keeps the rest of the finding honest.

**`observability.py`'s cardinality rule is stated and followed.** *"Every label value here is drawn from a bounded set… Nothing is labelled by customer, interaction, tenant or actor. That is a hard rule: a metric labelled by a user id is an outage waiting for a busy day."* Route templates, not raw paths. I checked the six metric definitions and the three scrape-time collectors; the rule holds in all nine.

**`usage_meter.py` refuses binary floating point for money**, with the reason written down: these values feed `numeric(14,4)` columns and are summed across millions of events, where float error accumulates into a real billing discrepancy (`:75-81`). The arithmetic is `Decimal` throughout. Only the *price* it multiplies by is wrong in two places (I3).

**No vendor hostname escapes its owning module.** Verified by grep across the whole backend for eight vendor hosts: zero hits in `main.py`, `db.py`, or any domain module.

---
## I1 — The LLM spend cap is a routing rule, not a limit

`llm_gateway/client.py` opens with a claim: *"LLM gateway client. All four profiles go through here when the flag is on."* Four profiles are declared at `:19` — `("voice", "text", "analysis", "internal")` — and each gets its own cap, read at `:24-27` from `LLM_GATEWAY_CAP_{PROFILE}_INR` with `LLM_GATEWAY_CAP_INR` as the fallback. `.env.example:304-305` ships two of them as commented defaults.

Four things are true about that cap, each verified from source, and together they mean it cannot do the job its name implies.

**It has one caller.** `maybe_chat` is imported in exactly one non-test place in the repository: `azure_openai.py:619`, inside `chat_with_tools`. Everything that reaches a chat model some other way is outside the gateway entirely. The single largest such path is the voice runtime — `voice/llm_pool.py:22` builds its own `AsyncAzureOpenAI` from a separate credential namespace (`AZURE_OPENAI_VOICE_*`, `voice/config.py`) and never calls `chat_with_tools`. That is not an oversight of mine or theirs: the prior audit found it too, and the split is defensible on its merits (a keep-alive async service against a sync tool loop). The consequence is what nobody wrote down.

**Two of the four profiles are unreachable.** `azure_openai.py:618` computes `gw_profile = "analysis" if profile == PROFILE_ANALYSIS else "text"`, and `PROFILE_CHAT`/`PROFILE_ANALYSIS` (`:38-39`) are the only profiles that module knows. So `"voice"` and `"internal"` can never be passed by the only caller. **`LLM_GATEWAY_CAP_VOICE_INR` is a documented configuration key that no code path can ever consult** — and it is the cap on the one workload that runs continuously, in real time, per call.

**When the cap trips, the request proceeds anyway.** `chat()` raises `RuntimeError(f"llm_gateway_spend_cap:{profile}")` at `:56` when `_over_cap` is true. The one caller wraps `maybe_chat` in:

```python
except Exception:
    logger.exception("llm gateway routing failed; Azure kill-switch")
```

and then falls straight through to the direct Azure client at `:635-643`. The design intends that channel for a *gateway outage* — fall back to Azure, which is correct and is what "kill-switch" means here. But a spend-cap breach travels the same channel, so hitting the cap does not stop the spend; it moves the spend onto the uncapped direct-Azure path and writes one `logger.exception` per request. **The control that exists to bound cost reroutes around itself when it engages.**

**The cap it does apply is per-process.** `_spend_inr` at `:21` is a module-level dict. Five containers run application code (`api`, `worker`, `bot_worker`, `voice`, `voice_insurance`), so a configured cap of ₹N is enforced independently in each process that reaches the gateway — the ceiling is a multiple of the number, not the number, and which multiple depends on how traffic happens to distribute. It also resets on every deploy.

I tested and discarded a fifth, worse reading before publishing it: that the cap never accumulates at all, because `_meter` computes cost inside a bare `except Exception: cost = 0.0` (`:174-179`). It does accumulate — `usage_meter.chat_cost_inr` exists at `usage_meter.py:94` and falls back to a hardcoded `_DEFAULTS` price book (`:33-44`), so it returns a non-zero Decimal even with no pricing env set. The cap is bypassable, not inert. That distinction is the difference between "this control is weaker than it looks" and "this control does nothing", and only the first is true.

### The meter cannot show you any of this

`azure_openai.py:725`, on the **fallback** path — the code that runs only when the gateway did *not* serve the request — records usage as:

```python
source_ref=f"llm_gateway.{gw_profile}" if _gw_on() else "azure_openai.chat_with_tools",
```

The condition is whether the gateway *flag* is on, not whether the gateway *handled the call*. So with `LLM_GATEWAY_ENABLED=true` and a gateway that is capped out, misconfigured, or down, every direct-Azure request is filed in the usage meter under `llm_gateway.text`. The one signal that would reveal the fallback is the signal that is overwritten by it. `maybe_chat` returns `None` whenever `base_url()` is empty (`:187-190`), so a deployment that turns the flag on and never sets `LITELLM_BASE_URL` sends 100% of its traffic direct to Azure and labels 100% of it as gateway spend.

**Fix.** Separate the two meanings that currently share one exception channel: let a gateway *failure* fall back, and let a *cap breach* raise to the caller. Label `source_ref` from what actually served the request rather than from the flag. Move `_spend_inr` behind the Postgres counter the platform already runs, or state in the docstring that the cap is per-process and advisory. Delete `LLM_GATEWAY_CAP_VOICE_INR` from `.env.example` or route the voice hop through the gateway — today the key promises a control that has no mechanism behind it.

---

## I2 — The shared "is this production?" helper is enforced across one package, and `main.py` is not in it

`env_utils.py:37-38` is the leaf helper:

```python
def env_name() -> str:
    """The declared environment, lower-cased. Unset means a laptop."""
    return (os.getenv("APP_ENV") or os.getenv("ENV") or "dev").strip().lower()
```

It exists because of a real refactor, and `tests/test_env_name_shared_helper.py` documents it with unusual care: the vault used to import a *private* name from the skill signer, so "the vault — which seals connector credentials and knows nothing about skill packs — [imported] the skill signer just to ask what `APP_ENV` says." The helper was promoted to a leaf module, and the test pins the result. It is good work.

The test pins it exactly twice. `test_both_key_helpers_use_the_leaf_implementation` asserts `sign.env_name is env_utils.env_name` and `vault_seal.env_name is env_utils.env_name` — the two *key* helpers, named in the docstring as the scope. And `test_no_module_still_reaches_for_the_old_private_name` scans for offenders with:

```python
for path in (BACKEND / "agent_core").rglob("*.py")
```

The scan stops at `agent_core/`. Three modules at the repository root answer the same question with their own copies, and none is covered:

| Module | Its own answer | Honours `ENV`? | Evaluated |
|---|---|---|---|
| `env_utils.py:38` | `APP_ENV` or `ENV` or `"dev"` | **yes** | per call |
| `main.py:204-205` | `APP_ENV` or `"dev"` | **no** | **once, at import** |
| `actor_context.py:55` | `APP_ENV` or `"dev"` | **no** | per call |
| `usage_meter.py:292` | `BILLING_ENV` or `APP_ENV` or **`"production"`** | no | per call |

`main.py` does not import `env_utils` at all — I grepped the whole file for it and got nothing.

**Why this one matters more than a tidiness complaint.** `_IS_PROD` at `main.py:205` is what decides, at `:3389-3396`, whether an inbound Twilio webhook without a valid `X-Twilio-Signature` is rejected:

```python
if not token:
    if _IS_PROD: ... return False
    return True
signature = (request.headers.get("x-twilio-signature") or "").strip()
if not signature:
    # Local ngrok tests sometimes omit; allow only outside production.
    return not _IS_PROD
```

The same constant also gates the hard requirement for an API key (`:432-433`), and whether `/docs`, `/redoc` and `/openapi.json` are served (`:588-590`).

So a deployment that declares itself with `ENV=production` and leaves `APP_ENV` unset splits in half. `env_utils.env_name()` reads `production`, and the signer and the vault correctly refuse to hand out their built-in development keys — the exact protection `env_utils`'s comment describes, working as designed. Meanwhile `main.py` reads `dev`, and the same process **accepts unsigned Twilio webhooks, does not require an API key, and publishes its OpenAPI schema.** The two halves of one decision disagree, and the half that fails open is the half facing the internet.

I have not found a deployment that sets `ENV` and not `APP_ENV`, and I did not look for one — `backend/.env` holds live secrets and was deliberately not read. The finding is that nothing prevents it and nothing would report it. `_IS_PROD` being a module-level constant also means it cannot be corrected without a restart.

**Fix.** One line: `main.py` imports `env_utils` and uses `env_name()`, as `sign` and `seal` already do. Then widen the offender scan from `(BACKEND / "agent_core")` to the backend root, so the next copy is caught by the test that already exists. The test is the right test; it is pointed at one package.

---
## I3 — Two price books for the same token, ten times apart

A collections platform that meters AI spend needs one answer to "what did that turn cost." There are two, in different modules, and they differ by an order of magnitude.

| Reader | Env key | Default | Used for |
|---|---|---|---|
| `usage_meter.py:96-97` | `PRICE_CHAT_INPUT_USD_PER_1M` | **0.25** | every metered event; the `usage_events` rows; the gateway spend cap |
| `main.py:3182` | `AZURE_OPENAI_INPUT_USD_PER_1M` | **2.5** | the Agent Studio prompt cost display |

Both are labelled. `.env.example:84` documents the Azure key as *"Studio prompt token/$ display (input only; cl100k_base via tiktoken)"*, and `usage_meter.py:35` documents its own as *"Chat: GPT-5-mini / gpt-4o-mini class."* Neither is a copy-paste accident, which is why this is worth stating carefully: the defect is not that two constants exist, it is that **neither is keyed to the deployment actually in use, and nothing reconciles them.**

`AZURE_OPENAI_CHAT_DEPLOYMENT` is a free-text deployment name (`.env.example:68`). Whatever model it points at has one real price. The meter prices every token at a mini-class rate; the Studio prices the same token at ten times that. At most one of them is right for any given deployment, both are silently wrong for a deployment of a different class, and the number an operator reads on screen before publishing a prompt is not the number that accrues against `LLM_GATEWAY_CAP_INR` (I1) or lands in the billing rows.

The `usage_meter` half is otherwise careful work — `_env_decimal` (`:75-87`) refuses binary floating point with an explicit rationale about `numeric(14,4)` columns and accumulated representation error across millions of events. The money arithmetic is right. The price is a guess in two places.

**Fix.** One price book, keyed by deployment name, read by both. If the Studio genuinely wants input-only pricing for a token-count preview, it should ask `usage_meter` for it rather than re-deriving it from a second env var.

---

## I4 — Every outbound hop is invisible except at the moment it dies

`observability.py` is the strongest module in this audit and it says why it exists: *"The audit's finding was that the system is operationally blind: no metrics, no traces, no structured logs, no error tracking… when a call went wrong there was no p95 to alert on and no way to answer 'is it Azure, the DB, or us?'"* It then closes the metrics and logging halves deliberately, declines to attempt traces with a stated reason, and enforces a hard cardinality rule (`:31-36`) that no label may be a customer, interaction, tenant or actor id. That rule is correct and it is followed.

What it instruments is six metrics — `http_requests`, `http_latency`, `http_in_flight`, `authz_denials`, `voice_calls_admitted`, `voice_calls_rejected` (`:76-113`) — plus three scrape-time collectors registered at `:293-299`: `db_pool`, `circuit_breakers`, and job-queue depth.

Read against the question this report asks, the shape is precise: **every one of those is an inbound or internal signal.** Not one outbound integration has a latency histogram or an error counter. The `circuit_breakers` gauge is the only provider-health signal in the system, and it covers the five named in-process breakers — `azure_openai`, `azure_openai_analysis`, `azure_speech`, `whatsapp_meta`, `minio`. That is genuinely useful, and it is a binary that trips after the threshold: you can see that Azure has been failing for five consecutive calls, and you cannot see Azure's p95 rising, or a 429 rate climbing, or a timeout budget being approached.

Every hop *without* a breaker is entirely dark. On the evidence assembled in §1 that list is: both Twilio clients, the LiteLLM gateway, Fish, Cartesia, Deepgram, ElevenLabs, OpenRouter, Azure Key Vault, the MCP connectors, Redis, and outbound tenant webhooks. A tenant's webhook endpoint can fail every delivery for an hour and the only trace is rows in `webhook_deliveries` and a log line — there is no counter to alert on and no dashboard that would show it.

The job-queue collector has the same shape of gap, and the prior audit found it too: `_JOB_QUEUES` at `:207` is `("bot_turn_jobs", "whatsapp_outbound_jobs", "kb_index_jobs")`. Webhook deliveries, campaigns, cadence, treatment, PTP and bounce queues are uncounted. I confirmed the tuple; the finding stands as that report wrote it.

**Fix.** One decorator or context manager in `observability.py` — `outbound_latency.labels(provider, operation)` and `outbound_errors.labels(provider, class)` — applied at the ten or so client entry points §3 nominates as canonical owners. The cardinality rule already tells you what the labels may be: provider name and operation, both bounded sets. This is the cheapest item in the report relative to what it buys, because the boundaries it must wrap are the same ones the canonicalisation work creates.

---
## I5 — Two signature-verified webhooks are rejected before they reach their signature check

This is the most consequential finding in the report, and it is entirely mechanical.

Authorisation policy lives in `authz.py`. Its `PUBLIC_ROUTES` tuple names the endpoints that carry no API key because they authenticate themselves, and it says so:

```python
# Delivery receipts. Twilio carries no API key, so the signature check
# inside the handler is the authentication — same as every other
# callback above.
("POST", "/twilio/sms/status"),          # authz.py:229
...
("POST", "/webhooks/collections/payment-events"),   # authz.py:233
```

Enforcement lives somewhere else. `main.py:233-257` defines a second, independent list, `_AUTH_EXEMPT_PREFIXES`, and `ApiKeyMiddleware` rejects anything not matching it before the route runs:

```python
auth_required = bool(single or key_map)
if auth_required and not provided:
    return JSONResponse({"detail": "unauthorized"}, status_code=401)   # main.py:294-295
```

The two lists disagree. `_AUTH_EXEMPT_PREFIXES` contains `/webhooks/whatsapp`, `/webhook/whatsapp`, the four `/twilio/voice/*` callbacks, `/pay`, `/webhooks/payments`, `/ws` and `/.well-known/agent-card.json`. It does **not** contain `/twilio/sms/status`. And `/webhooks/collections/payment-events` is not covered by `/webhooks/payments` — prefix matching is `path == p or path.startswith(p + "/")`, and `/webhooks/collections/...` does not start with `/webhooks/payments/`.

So on any deployment with `API_KEY` or `API_KEY_MAP` set — which is to say every deployment that has followed the production checklist, since `main.py:432-433` raises at boot without one — both endpoints return `401` to the sender. The handler at `main.py:3669` never executes; the signature it would have validated is never read.

**What that costs.** `/twilio/sms/status` is the delivery-receipt callback. Without it, `contact_delivery_events` keeps the `sent` row written at send time by `twilio_sms._record_sent` and never receives `delivered`, `undelivered` or `failed`. The SMS path is the fallback used when WhatsApp is outside its 24-hour window — so the channel of last resort is precisely the channel with no delivery evidence. `twilio_sms.status_callback_url` has a careful docstring arguing that returning `""` is better than a localhost guess, because *"a configuration error that announces itself as 'no receipts' is better than one that announces itself as 'borrowers on this channel are unreachable'."* The reasoning is right and the outcome it was written to avoid is what ships: receipts are configured, sent, and refused at the door.

`/webhooks/collections/payment-events` is the bounce-ingest hook. A real payment bounce arriving there is rejected, so no statutory pay-link is raised from it.

**Why it happened is visible in the code.** The comment above the exempt list records an incident:

> `ONLY the inbound webhook is exempt, and it enforces X-Twilio-Signature itself. Exempting all of /twilio left POST /twilio/voice/outbound open to the internet — anyone could dial arbitrary PSTN numbers on our account — and leaked the phone number / media-stream URL via /twilio/voice/status.`

That was a serious hole and closing it was right. The fix replaced a `/twilio` prefix with an explicit enumeration — and the enumeration covered the four voice callbacks the author was looking at. `/twilio/sms/status` was added to `authz.py` later, by someone reading the authorisation policy, who had no reason to know a second list existed in `main.py`. **The security fix is what created the availability bug**, and neither list references the other.

Nothing catches it: `tests/test_production_hardening.py` asserts the four voice paths and never mentions `/twilio/sms/status`, which appears in no test file at all (grep across `tests/`: zero hits).

**Fix.** Derive one list from the other. `authz.PUBLIC_ROUTES` is the policy statement and already carries the reasoning; `_AUTH_EXEMPT_PREFIXES` should be computed from it, or a test should assert the two agree. That test is three lines and it is the same shape as the guard `tests/test_env_name_shared_helper.py` already applies to a different pair of lists (I2).

---

## I6 — The SSRF guard resolves an address, discards it, and connects by name

`webhooks_dispatch.resolve_public_host` (`:132-152`) is good security code, reused rather than reimplemented by `agent_core/connectors/persist.py:50`. It forces https, resolves via `getaddrinfo`, and rejects if **any** answer is private, loopback, link-local, reserved, multicast or unspecified, treating an unparseable answer as private. `tests/test_connector_ssrf_guard.py` covers thirteen cases including the `169.254.169.254` metadata literal and mixed public/private answer sets, and asserts the guard runs *before* the POST.

Then both call sites throw the answer away.

```python
resolve_public_host(job["url"])                                  # webhooks_dispatch.py:438
...
http_status, body = _post(job["url"], headers=headers, ...)      # :448
```

The return value is unassigned at `:438`. In the connector path, `_guard_outbound_url` returns the URL *string*, not the vetted address, and `persist.py:360` posts to that hostname. In both cases `httpx` performs its own, later, independent DNS lookup. A resolver that answers public on the first query and private on the second passes the guard and reaches the internal address — the classic rebinding window, wide open by construction.

The unusual part is that the codebase already knows. `ops_screens.py:73-77`, in the *registration*-time validator, explains why it deliberately does not resolve there and states the requirement for the send path in full:

> `NOTE: hostnames are deliberately *not* resolved here — DNS at validation time is both a rebinding hazard (the name can resolve differently at send time) and a blocking network call inside a request handler. Before real webhook egress ships, the delivery worker must re-check the resolved address immediately before connecting and pin it for the request.`

The delivery worker does the re-check. It does not do the pin. **The specification and the implementation are in the same repository, written by people who understood the threat exactly, and the half that shipped is the half that does not close it.**

Two smaller gaps in the same guard: an IPv4-mapped IPv6 literal (`::ffff:10.0.0.1`) is reported as non-private by `ipaddress.ip_address`, so it passes; and there is no port restriction.

**Fix.** Pass the resolved address to the transport instead of discarding it — an `httpx.HTTPTransport` bound to the vetted IP with the original `Host` header preserved for TLS/SNI. `resolve_public_host` itself needs no change beyond the mapped-IPv6 case; it is correct and tested. Extend `tests/test_connector_ssrf_guard.py` rather than starting a new file.

---

## I7 — The gateway answers a rate limit by tripling its request rate

`llm_gateway/client.py:112-131` is the retry loop:

```python
retries = 2
for attempt in range(retries + 1):
    try:
        resp = httpx.post(base_url() + "/chat/completions", json=payload, headers=headers, timeout=timeout or 20.0)
        if resp.status_code >= 500 and attempt < retries:
            continue
        resp.raise_for_status()
        ...
    except Exception as exc:
        last_exc = exc
        if attempt >= retries:
            break
```

Three defects in nine lines, each verified:

**No delay.** The `continue` on a 5xx re-issues the request immediately. There is no `sleep`, no backoff, no jitter anywhere in the module.

**429 is retried on the exception path, also with no delay.** A 429 fails the `>= 500` test, reaches `raise_for_status()`, raises, is caught by the bare `except Exception`, and the loop runs again. `Retry-After` is not read. The system's response to "you are sending too fast" is to send the same request twice more as fast as it can. Across the codebase, `azure_speech.py` is the **only** module that reads a `Retry-After` header at all.

**The retried verb is not idempotent.** A `ReadTimeout` on `/chat/completions` does not mean the completion was not generated; it means the answer did not arrive. Retrying bills it again and may deliver a second, different completion. This is the precise hazard `whatsapp_outbound.py:236-241` refuses by name — any error where the provider may already have accepted the request is dead-lettered rather than retried, to avoid a double send. Two modules in one repository hold opposite policies for the same failure, and the one that gets it right documented why.

**And the gateway silently drops a parameter it accepts.** `chat()` takes `reasoning_effort` (`:48`) and never forwards it to `_http_chat` (`:60-69`); `_http_chat`'s signature has no such parameter. `azure_openai.py:621-630` passes it in good faith. The direct-Azure path documents what that parameter is worth, measured: *"the KB planner measured 3.26s at the default and 0.86s at 'low' on the same prompt, with an identical tool call out."* So turning `LLM_GATEWAY_ENABLED=true` silently regresses that call by roughly 3.8×, with no error and nothing in the response to indicate the setting was ignored.

**Fix.** The retry policy `azure_speech.py:378-410` already implements — bounded attempts, `Retry-After` with a cap, full jitter, and the `_SpeechRetryable` trick of converting a retryable *response* into an *exception* so a circuit breaker can count it — is the one to lift. Add an idempotency flag so a policy can be told a verb must not be replayed, which is what `whatsapp_outbound` needs and would otherwise lose. Forward `reasoning_effort` or remove it from the signature; accepting a parameter and discarding it is worse than not accepting it.

---
## I8 — Configuration that is documented, unread, and pinned by a test

`.env.example` is 638 lines: **161 live keys and 81 more commented out**, 242 knobs in total. It is a well-written file — most keys carry a comment explaining the trade-off, and several explain a past incident. The problem is that it is not derived from anything, so it drifts in both directions at once.

**Documented and read nowhere.** Three keys advertise a model override that does not exist:

| Key | `.env.example` | Reality |
|---|---|---|
| `CARTESIA_MODEL=sonic-3.5` | `:528` | `provider_tts.py:118` hardcodes `_CARTESIA_MODEL = "sonic-3.5"` |
| `DEEPGRAM_TTS_MODEL=aura-2-thalia-en` | `:536` | no reader anywhere |
| `ELEVENLABS_TTS_MODEL=eleven_multilingual_v2` | `:546` | hardcoded at `provider_tts.py:194` |

Grep across the repository returns no `os.getenv` for any of the three. An operator who edits one gets no effect and no error — the change simply does nothing, which is the least debuggable outcome available.

The Cartesia case has a twist. `tests/test_provider_preview_routing.py:86-87` asserts:

```python
assert provider_tts._CARTESIA_MODEL != "sonic-2"
assert provider_tts._CARTESIA_MODEL == "sonic-3.5"
```

That test is doing something reasonable — pinning a deliberate model upgrade so nobody reverts it silently. But the combined effect is that the hardcode is enforced by CI while `.env.example` tells the operator it is configurable. The documentation and the test now assert opposite things about the same value.

**Read but undocumented.** In the other direction: `WEBHOOK_DELIVERY_TIMEOUT_SEC`, `AZURE_SPEECH_MAX_RETRIES`, `AZURE_SPEECH_MAX_CONCURRENCY`, `AZURE_TTS_CACHE_MAX_BYTES`, `AZURE_TTS_CACHE_MAX_AGE_S`, `LITELLM_MODEL` and `LLM_GATEWAY_{PROFILE}_MODEL` are all live and none appears in `.env.example`. These are exactly the knobs an operator reaches for during an incident — the retry count and the concurrency limit on the busiest provider.

**Aliased names that fail silently.** `llm_gateway/client.py` is the only module in the codebase that accepts two names for one setting: `LITELLM_BASE_URL || LLM_GATEWAY_URL` (`:39`), `LITELLM_API_KEY || LLM_GATEWAY_KEY` (`:89`), `LLM_GATEWAY_{P}_MODEL || LITELLM_MODEL || "azure/chat"` (`:90`). Setting the wrong half of any pair produces no warning; the gateway simply reports `llm_gateway_url_missing` or falls through to Azure (I1).

**One variable, four validity rules.** `PUBLIC_BASE_URL` is parsed independently in four places with three different notions of valid: `twilio_sms.status_callback_url` (`:40-41`) requires `startswith("http")` and returns `""` otherwise; `voice/twilio_ops.voice_public_base_url` (`:117-122`) gates on `ws_proxy_enabled()`; `voice_https_public_base_url` (`:125-136`) raises on `http://`; and `main._twilio_signature_ok` (`:3403`) uses it raw to rebuild the URL Twilio signed. A value that is valid for the signature check and invalid for the callback URL yields an endpoint that verifies signatures for callbacks it never asked to receive.

---

## I9 — Where the vendor gets into the domain

The brief asked specifically for provider-specific logic leaking into the business layer. The honest answer has two halves, and the good half is worth stating first.

**No vendor hostname appears outside its owning module.** I grepped the whole backend for `graph.facebook.com`, `api.cartesia.ai`, `api.deepgram.com`, `api.elevenlabs.io`, `openrouter.ai`, `fish.audio`, `speech.microsoft.com` and `vault.azure.net`. Zero hits in `main.py`, in `db.py`, or in any domain module. Endpoint knowledge is properly encapsulated everywhere. That is a real structural property and most codebases this size do not have it.

What leaks is **envelope shape**, not endpoints.

**Meta's webhook envelope is parsed inside `db.py`.** `db.process_whatsapp_webhook` at `db.py:10886` walks `payload["entry"][].changes[].value.{contacts,messages,statuses}` and unwraps `interactive.button_reply.title` and `list_reply.title` — the Graph API's exact JSON shape, inside the persistence module. It imports `whatsapp` for one function, `normalize_phone`. Every other piece of Meta knowledge in the system — the signature check, the error taxonomy, the PII-stripping classifier — lives in `whatsapp.py`. The envelope parser is the one piece that does not, and it is in the largest file in the repository.

**Twilio's form-field names appear in five route handlers.** `CallSid`, `CallStatus`, `AnsweredBy`, `StreamEvent`, `ErrorCode`, `MessageSid`/`SmsSid`, `MessageStatus`/`SmsStatus` are read directly in `main.py:3573-3720`. The contrast is instructive: `delivery_receipts.normalise_twilio` (`:44-63`) already exists and does exactly the right thing for the status *vocabulary*, translating Twilio's words into the system's own. The *field names* never received the same treatment, so the vendor's spelling reaches the route layer while its vocabulary does not.

**And `db.py` is 18,087 lines.** That is the context for both leaks. A file that large has no boundary to be outside of: it sends WhatsApp messages, calls `embed_texts`, mints `minio://` references, and parses vendor webhooks, because every one of those is "just another function in db". The leakage findings above are symptoms of that, and no integration boundary can be enforced against a module that contains the whole domain.

---
## I10 — Row-level security is complete, correct, self-protecting, and switched off

`rls.py` is 633 lines of careful work. It derives per-table policies from the foreign-key graph, applies `ENABLE` *and* `FORCE ROW LEVEL SECURITY` (`:477-480` — correctly closing the table-owner bypass that catches most first attempts), and verifies row counts inside the same transaction that applies the DDL, rolling back on mismatch. Its docstring states the threat precisely:

> `Every tenant predicate in this codebase is written by hand in Python. That works until one is forgotten, and a forgotten predicate is not a crash — it is one tenant reading another's rows, returned with a 200.`

It then names the three conditions that make switching it on safe, and enforces all three. The second one is the finding:

> `**The connecting role must not bypass RLS.** Superusers and roles with BYPASSRLS ignore policies entirely, and the application currently connects as one. Enabling RLS as that role changes nothing at all while looking like it worked, which is worse than not enabling it — so `enable` refuses, and `status` leads with it.`

That is an accurate description of the deployed configuration. `docker-compose.yml:37-38` sets `POSTGRES_USER`/`POSTGRES_PASSWORD` to `collections`/`collections` — the image's superuser, therefore BYPASSRLS. `rls.provision_role` (`:600-620`) exists to mint a `NOSUPERUSER NOBYPASSRLS` role and **nothing calls it**.

Searching the whole backend for `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY` or `CREATE POLICY` returns exactly two files: `rls.py` itself and `tests/test_rls.py`. **Zero of the 102 Alembic migrations and zero of the 26 `sql/*.sql` files apply any policy.** The only caller of `rls.enable()` is `scripts/rls.py`, a manual CLI. Two further modules state the live position independently — `agent_core/connectors/first_party.py:26` and `tests/test_connector_read_hygiene.py:8` (*"RLS is opt-in and the app connects as BYPASSRLS"*).

So the last line of defence is built, tested, and inert. Tenant isolation in production rests entirely on hand-written predicates — and the analyst counted **70 of them in `db.py` alone, spelled four different ways** (`:tenant_id` ×52, `:t` ×9, `:tenant` ×8, `:tid` ×1) against **364 `SELECT` literals** in that file.

There is also an ordering trap that is written down nowhere: because the app connects as a superuser, `rls.enable()` would *refuse* today. Switching RLS on is not one step but three — provision the restricted role, change the connection string, then enable — and the sequence exists only in the reader's head.

**One measured instance of the exact failure this guards against has already occurred.** `tests/test_cross_tenant_reads.py` seeds a rival tenant and asserts non-leakage behaviourally rather than by inspecting SQL; its header records that a prior sweep found seven accessors bounded but not tenant-scoped, `list_callbacks` having no `WHERE` clause at all. The class of bug is real in this codebase, was caught once by a test rather than by review, and the structural control that would catch the next one is off.

**And one path has no predicate today.** `kb_retrieve.py:713-729` joins `kb_documents d` — which does carry `tenant_id NOT NULL` — and filters only on `c.embedding IS NOT NULL AND d.enabled AND d.status='indexed'`. `d.tenant_id` is never referenced. The FAQ half (`:752-763`) is weaker: `faq_pairs` has no `tenant_id` column at all and reaches a tenant only through a *nullable* `linked_document_id`. The tell is `kb_retrieve.py:385-390`, which puts `tenant_id` in the *cache* key and explains it is *"a path that cannot inherit whatever tenant scoping the SQL applies"* — written as though the SQL applied some. Tenancy is threaded through the cache, the logs and the retrieval records, and not through the query. This is latent rather than exploitable while the deployment is single-tenant, and there is no compensating control behind it.

**Fix, in order.** `rls.provision_role`, then the connection string, then `rls.enable()` in a migration rather than a CLI — and write the ordering down. Independently of RLS: give `kb_chunks` and `faq_pairs` a tenant root and add the predicate, because RLS would otherwise make unlinked `faq_pairs` invisible to *every* tenant and silently kill half of hybrid retrieval.

---

## I11 — One unique violation, three status codes, and one bare catch in the money path

`pg_errors.py` is 29 lines and exactly the right shape: one decision, one place, handling both the `.orig`-wrapped and raw psycopg forms and both the `sqlstate` and `pgcode` spellings. Its docstring names the drift it exists to prevent — *"so it cannot drift between the job queues, the WhatsApp ingest path and db.py."* It has five call sites, all in worker and ingest paths, all correct.

It classifies one SQLSTATE, 23505. Everything else diverges.

**On the API surface, an `IntegrityError` becomes one of three answers depending on which route it hits.** `_handle_write` (`main.py:720-734`) maps it to **409** and is used at 82 of roughly 160 write routes. About 34 DB-touching write routes have no guard at all and return an unhandled **500** — `POST /webhook-endpoints` (`:1449`), `POST /kb/faqs` (`:4499`), `POST /kb/snapshots` (`:4552`), `POST /providers/bindings` (`:5364`) were each read and confirmed to have no try/except. Six KB routes convert it to **502** (`:4310, 4356, 4399, 4464, 4486, 4580`). There is no global handler to catch the remainder: `main.py` registers four exception handlers and none of them is for `Exception` or `SQLAlchemyError`.

The 502 group deserves credit for its motive and criticism for its result. `main.py:4357-4358` explains those handlers exist to stop `str(exc)` leaking DSNs and Azure error bodies to a client — correct, and the same instinct that keeps `/ready` from stringifying its DSN. But a client-caused duplicate key reported as an upstream gateway failure is unactionable for the caller and pollutes 5xx alerting for the operator.

**`payment_events.py:361` is the one that matters most.** In the payment-bounce ingest path:

```python
except IntegrityError:
    raced = conn.execute(text("SELECT * FROM payment_events WHERE tenant_id = :tid AND source = :source AND source_ref = :ref FOR UPDATE"), ...)
    ...
    if raced is None and emi is not None:
```

No exception binding, no SQLSTATE check, no call to `pg_errors`. It assumes any integrity error is the source-ref race it is written to absorb. A foreign-key violation on `customer_id`, `account_id` or `emi_installment_id`, or a CHECK failure on `kind`/`reason`, takes the same branch: the probe finds nothing, `raced is None`, and a genuine data-integrity fault is processed as an idempotent replay of a bounce event. `db.py:10679` shows the correct form a few thousand lines away — `if not _is_unique_violation(exc): raise`.

**Deadlock is unhandled everywhere, and the codebase says it should not be.** Zero occurrences of `40P01`, `40001`, `serialization_failure` or `deadlock` as SQLSTATE handling anywhere in the backend; no `tenacity`, no `backoff`. `db.py:12043` explicitly names deadlock as something that must surface — and it surfaces as an unhandled 500 on the API and a swallowed `except Exception` in most worker loops. With `FOR UPDATE SKIP LOCKED` queues, multi-row updates and five processes against one database, 40P01 is not exotic. The team already knows the right shape: `capture.py:1396-1421` handles turn-allocation contention with `ON CONFLICT … DO NOTHING RETURNING` plus a bounded loop, sidestepping SQLSTATE entirely. It is a better design than a retry, and it is applied to exactly one table.

**Fix.** Extend `pg_errors.py` past 23505 to 23503/23502/23514 and 40P01/40001 — it is 29 lines and already the canonical shape — and make `_handle_write` or a global `SQLAlchemyError` handler the only path from a database exception to a status code. Bind the exception at `payment_events.py:361` and ask the classifier.

---

## I12 — Only one of the four connection bounds is set, and the budget holds only under compose

`db.py:141-147` passes `statement_timeout` and `app.tenant_id` as libpq **startup parameters**, which is a genuinely good decision: the GUC is set before the connection can execute anything, and because it is a session default rather than a transaction-scoped `SET`, no `ROLLBACK` — including the pool's return-to-pool rollback — can revert it. The transaction-scoped override at `:152-168` correctly uses `SET LOCAL`, and its string interpolation is safe *only* because `tenant_context.validate()` constrains the value to `[A-Za-z0-9._:-]{1,128}` first, Postgres not accepting a bind parameter in `SET`. The reasoning is written out at `:126-137`.

Of the four bounds that matter, that is the only one set. Repository-wide: `connect_timeout` — **0 hits**. `pool_timeout` — **0 hits** (SQLAlchemy default, 30s). `idle_in_transaction_session_timeout` — **0 hits**. `lock_timeout` appears only in `tests/test_job_claim.py`.

**No `connect_timeout` is the sharp one.** libpq's default is unbounded, so against a black-holed Postgres — a network partition, not a refused connection — a checkout blocks on TCP until the kernel gives up, typically ~130s on Linux. Because `pool_pre_ping=True` puts that on the *checkout* path, request threads pay it rather than a background reconnector; with `pool_timeout` at 30s, waiters queue behind a connect that will not return for four times that. And `/ready` itself calls `engine.connect()` (`db.py:341`), so the health check hangs instead of reporting 503 — the load balancer loses the ability to shed load at the moment it is most needed.

**No `idle_in_transaction_session_timeout` is the more consequential omission**, because `statement_timeout` bounds a running statement, not an open transaction with nothing executing. A process that stalls between two `execute()` calls holds its locks and its snapshot indefinitely. What prevents that today is discipline, not the database — see below.

**The connection budget is off by one service and only true under compose.** `docker-compose.yml:3-7` states a budget of "sum ≈ 25" and enumerates api 5+5, worker 3+2, bot_worker 3+2, voice 3+2. It omits `voice_insurance` (2+1), which the same file defines at `:231-232`. The real total is **28**, which is still comfortable against `max_connections=100`.

The number stops being true outside compose. `run_stack.ps1:43-47` launches the same five processes bare-metal with no pool environment set at all. There, `worker` and `bot_worker` call `load_env()` before importing `db` and pick up `.env.example:194-195` (`DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=10`) → 15 each; `main.py` never calls `load_env()` at all and falls through to `db.py:117-118`'s hardcoded defaults — which are *also* 5 and 10 → 15. **The two paths agree at 15 per process by coincidence**, because `.env.example`'s values happen to equal the code defaults. Worst case bare-metal is 5 × 15 = **75**, leaving roughly 22 connections for everything else — one `alembic upgrade`, a `psql` session and the corpus simulator can take that. `db.py:55-64` warns about precisely this class of accidental agreement for `TENANT_ID`; the pool values have the same property and no warning.

**The discipline that is holding this together is real, and worth naming.** The analyst scanned all 618 `engine.begin()`/`connect()` blocks across the backend for external I/O held inside a transaction — `await`, `httpx`, `requests`, `time.sleep`, embed calls, LLM calls, storage calls, subprocess, nested acquisition. **Three hits, all false positives** (two `minio://` string literals and a config lookup). The only real instance is `kb_ingest.py:480-481`, which holds a connection idle-in-transaction across a batched Azure embedding call — on a background worker, off the request path, one line to fix.

That is a better result than most codebases would produce, and it is not an accident: the rule is written down in three separate places, including `call_closer.py:1098-1105` — *"An LLM call inside `engine.begin()` holds a pooled connection and a row lock for the whole of its latency, which is exactly what `qa_autoscore` documents as the thing not to do."* The pool-exhaustion hypothesis I asked the analyst to hunt is **refuted on the request path.** But nothing structural preserves it: there is no session helper anywhere — zero `sessionmaker`, zero contextmanager in `db.py`, zero FastAPI `get_db` dependency — so all 618 sites re-open the engine inline and the rule survives on convention and three docstrings.

**Fix.** Add `connect_timeout` and `idle_in_transaction_session_timeout` to `connect_args`. Correct the compose header to 28 and include `voice_insurance`. Set the pool variables explicitly in `run_stack.ps1` rather than relying on two independent defaults happening to match.

---
## I13 — The `recordings` bucket is never created, so call audio lands in the knowledge-base bucket

`storage.py` has exactly one `make_bucket`, at `:135-136`, inside `ensure_bucket()`, and it provisions one bucket: `get_bucket()`, i.e. `MINIO_BUCKET`, default `collections-kb`. The rule is stated where it matters, at `storage.py:239`:

> `# Bucket provisioning is owned by ensure_bucket(); do not create here.`

That is a good rule. The problem is what the callers ask for. `voice/recording.py:74-81`:

```python
if storage.is_configured():
    try:
        storage_ref = storage.put_bytes(key, wav, "audio/wav", bucket="recordings")
    except Exception:
        storage_ref = storage.put_bytes(key, wav, "audio/wav")   # ← no bucket → collections-kb
```

`voice/persist.py:1332-1339` does the same for transcript exports with `bucket="transcripts"`. Neither bucket exists, and nothing creates them. So the first `put_bytes` raises `NoSuchBucket` → `StorageUnavailable`, the bare `except Exception` catches it, and the retry writes into the default bucket. **This is not an edge case — it is the only outcome, on every call, because the bucket is never created.**

Three consequences, in order:

**Call recordings and transcripts are stored in `collections-kb`**, at keys `recordings/{tenant}/{id}.wav` and `transcripts/{tenant}/{id}.transcript.json`, sharing one bucket and therefore one access policy with knowledge-base policy documents.

**The fallback is silent.** The `logger.exception("minio upload failed — falling back to local disk")` sits on the *outer* try and fires only if both attempts fail. A successful cross-bucket write logs nothing at all.

**It burns the shared circuit breaker.** Both attempts run through the `minio` breaker, whose threshold is 5 (`circuit_breaker.py:44`), so roughly three recordings open it — and the open circuit then fails **KB uploads**, an unrelated feature. One missing bucket takes down a second subsystem.

Across the codebase, `minio://` references name **seven distinct buckets** — `collections-kb`, `recordings`, `transcripts`, `dispute-evidence`, `documents`, `export-bundles`, `kb-sources`, `waveforms` — and the code creates one.

**Fix.** A `BUCKETS` registry that `ensure_bucket` iterates, and a `bucket=` argument that fails loudly rather than silently retrying somewhere else. That one change closes all three consequences.

### The `minio://` references that point at nothing — confirmed, with the consequence corrected

The prior audit found that dispute evidence, generated documents and export bundles mint `minio://` references without ever uploading. **The write half is confirmed on all four paths**: `db.py:5416-5417`, `db.py:6561,6564`, `followups_db.py:872`, and the seed data. `put_bytes` has five call sites in the whole repository and none is reachable from any of them. `followups_db.py:853` says so plainly — `# Demo: mark ready immediately (no real zip/pdf pipeline yet)` — and still sets `status='ready'`.

**The consequence in that report is wrong, and the correction matters.** It states that a user downloading dispute evidence gets a 404, 500 or an empty file. There is no download to attempt. The read paths do not select the column: `_dispute_evidence` (`db.py:1672-1695`) returns `id, filename, mime_type, created_at, uploaded_by` and never `storage_ref`; `list_documents` (`db.py:2441-2452`) returns `generated_at, size_bytes`. `presign` appears **zero times** in the repository and `storage.get_bytes` has exactly one caller anywhere — `kb_ingest.py:239`. Nothing is served from object storage at all. These are dead metadata columns and demo scaffolding, not a broken feature.

Two things the prior audit missed are worse than what it found.

**A seeded knowledge-base row points at a bucket the code never writes, and that one *is* dereferenced.** `seed_postgres.py:1205` writes `kb_source_files.storage_ref = "minio://kb-sources/hdfc.retail/rbi-disclosures.pdf"`, while the live upload path writes `minio://collections-kb/kb/{doc_id}/{name}`. `kb_ingest._load_source_text` (`:221-243`) prefers the latest `kb_source_files` row and calls `get_bytes` on it — so **re-indexing a seeded document raises `StorageUnavailable` and counts against the `minio` breaker.** Its docstring promises cover that does not exist: *"Prefer latest MinIO `kb_source_files` row; fall back to disk `source_path`"* — but the disk fallback is reached only when **no row exists** (`:233`), never when the fetch *fails*.

**A comment asserts the opposite of the line beneath it.** `db.py:5415-5417`:

```python
# Storage layout is the server's concern — clients don't dictate paths.
"storage_ref": payload.get("storageRef")
or f"minio://dispute-evidence/{_tenant()}/{dispute_id}/{payload['filename']}",
```

`EvidenceCreateRequest.storageRef` (`schemas.py:919`) is client-supplied and takes precedence over the server-built path, and `payload['filename']` is interpolated **unsanitised** — bypassing `storage._safe_segment`, which exists for exactly this. Compare `db.py:6318`, *"server owns storage_ref; never trust a client path"*, where `_ensure_document_file` genuinely builds the reference from `document_id` and lets the client's filename affect only the display name. That one delivers what it claims. This one is a pre-planted path traversal, latent only because nothing reads the column yet.

**And there are three reference schemes for one parser.** `parse_storage_ref` (`storage.py:200-211`) accepts only `minio://` and raises `ValueError` on anything else. The codebase also writes `local://` (recordings and transcripts, when MinIO fails entirely) and `voicemail://` (`voice/amd.py:333`, a zero-byte placeholder). `local://` paths point into `/app/.cache/recordings`, which is **not a volume** — `docker-compose.yml:246-249` declares only `pgdata`, `minio_data` and `voice_sessions`, and the `voice` container mounts nothing there. So the artefact is lost on restart while the `interaction_media` row survives and still claims it exists. One consumer does surface these: `agent_core/live_qa/pack.py:255` emits `"storageRef"` into a QA pack, so `local://` and `voicemail://` references do reach a reader.

---

## I14 — Transcripts are redacted on the way to the model and not on the way to disk

`transcript_view.py:53-57` states the principle, and states it well:

> `Redacted before the prompt is assembled rather than on the way out: an identifier must never leave the process at all.`

It implements two passes — `pii_redact.redact_text`, plus `scrub_identifiers` for the bare digit runs that speech-to-text emits unformatted, which the first pass misses because they carry no formatting to match on. That second pass is the kind of detail you only add after seeing a real transcript.

`voice/persist.py:export_transcript_json` (`:1302-1362`) serialises `list_transcript_turns()` (`:1267-1299`), which returns `r["text"]` **verbatim**. No `redact_line`, no `pii_redact`, no `scrub_identifiers`.

| Destination | Redacted |
|---|---|
| LLM prompt (`fenced_transcript`) | yes — both passes |
| Object store / local disk (`export_transcript_json`) | **no** |
| `/interactions/{id}/export` JSON and Markdown | **no** — grep for `redact` or `pii` across `voice/call_export.py`, `voice/flow_export.py`, `agent_core/policy_export.py` and `capture.py` returns zero hits |

There is no separate redacted copy and no prefix separating raw from redacted, because raw and redacted are the same artefact. Combined with I13, an unredacted call transcript containing whatever the borrower said aloud — card numbers, account numbers, dates of birth — is written into the knowledge-base bucket.

The pattern that fixes this already exists in the repository and is already articulated. `pii_redact.py:68-71` explains why `audit_args` is applied *inside* `bot_jobs.record_tool_call` rather than at each call site: **"the redaction is a property of writing the row rather than of remembering to call it."** Tool-call arguments in an export bundle inherit that protection. The transcript text beside them does not.

**Fix.** Route `export_transcript_json` and `call_export.build_bundle` through `transcript_view.redact_line`. Any shared helper must keep **both** passes — `pii_redact.redact_text` alone misses the unformatted digit runs, which is the failure mode `transcript_view.py:40-47` was written to catch.

---

## I15 — MinIO has a 300-second timeout, and the breaker's docstring describes the consequence

`storage.py:113` constructs `Minio(...)` with no timeout argument. The pinned `minio==7.2.20` defaults to `timedelta(minutes=5).seconds` for both connect and read (`minio/api.py:167-178`), with `urllib3.Retry(total=5, backoff_factor=0.2, status_forcelist=[500,502,503,504])`. PUT is in urllib3's default retryable set, so a knowledge-base upload against a black-holed endpoint can take **six attempts of five minutes — about half an hour** before it fails.

The breaker's own docstring, at `circuit_breaker.py:85-89`, describes this configuration exactly:

> `a probe that never returns (hung socket, no client-side timeout) would otherwise hold the slot forever and wedge the breaker open permanently.`

The breaker mitigates the wedge with probe-slot ageing. It cannot shorten the 300 seconds. With `reset_timeout_s` defaulting to 60, **a single half-open probe can outlive five reset windows.**

**And `delete_object` bypasses the breaker entirely.** `put_bytes` and `get_bytes` go through `_minio_breaker().call(...)` (`:221-223`, `:256-257`); `delete_object` (`:278-291`), `ping` (`:143-156`) and `ensure_bucket` (`:128-141`) call the client directly. Two consequences: deletes never fail fast, so `_kb_delete_minio_refs` looping over a 20-file document (`db.py:15309-15326`) can block for over an hour *while the breaker is actively telling every other caller the dependency is down*; and deletes never *open* the breaker either, so a MinIO that fails only on DELETE stays invisible to it. `ping` bypassing is defensible — a probe should measure reality rather than the breaker's opinion — and the breaker's docstring at `storage.py:159-165` shows the author reasoning carefully about what should and should not count. The delete asymmetry looks unintended by contrast.

**One related mapping bug.** `main.py:712-717` registers `@app.exception_handler(CircuitOpenError)` → 503, and `_handle_write` correctly lets it through. But `kb_upload_document` (`:4460-4466`) and `kb_new_version` (`:4484-4490`) end in a broad `except Exception: raise HTTPException(502, "kb_upload_failed")`. `CircuitOpenError` is a `RuntimeError`, so it is swallowed there and the app-level handler never fires — **the client gets 502 (upstream is broken, retrying is hopeless) instead of 503 (dependency shed, retry later), on the only two routes where the MinIO breaker can trip.**

**What is right here, and worth keeping.** The credential fallback guard is sound: `_is_loopback_endpoint` (`storage.py:76-93`) was traced branch by branch — `minio.evil.com`, `127.0.0.1.evil.com` and `0.0.0.0` all correctly classify as remote, and production raises regardless of endpoint. And the KB upload path is the best-engineered piece of the storage surface: `db.py:15486-15514` puts to MinIO *first*, then opens the database transaction, with `_discard_orphan_object` compensation on failure and a comment explaining the orphan-blob reasoning — the whole sync path wrapped in `asyncio.to_thread` at `main.py:4443`. That is the correct ordering and it was arrived at deliberately.

---
## I16 — `/metrics` publishes the exact number another module refuses to publish, for the reason that module gives

This is the clearest single illustration of the pattern running through this report, and both halves are four lines apart in the same repository.

`voice_sandbox.py:98-105` declines to report voice capacity unless the pipeline is running in-process, and says why:

> `# Capacity is reported ONLY on the embedded path. The counter is`
> `# process-local (see voice/admission.py), so when the pipeline runs in a`
> `# separate `voice` container this process's counter is permanently zero`
> `# — reporting it would be worse than reporting nothing, because it would`
> `# read as "plenty of headroom" during an overload.`

That is exactly right, and it is gated on `embedded_host_enabled()`.

`observability.py:194-201` is the Prometheus collector for the same three numbers:

```python
def _voice_samples() -> Iterable[tuple[str, dict[str, Any], float]]:
    from voice import admission
    snap = admission.snapshot()
    yield ("voice_calls_active", {}, float(snap.get("activeCalls") or 0))
    yield ("voice_calls_max_concurrent", {}, float(snap.get("maxConcurrentCalls") or 0))
    yield ("voice_calls_high_water_mark", {}, float(snap.get("highWaterMark") or 0))
```

No guard. It is registered unconditionally at `main.py:428`, in the **api** process. `VOICE_EMBEDDED_HOST` defaults to `false` (`.env.example:336`) and compose does not set it — the pipeline runs in the separate `collections_voice` container. So in the shipped topology, `/metrics` reports `voice_calls_active 0` and `voice_calls_max_concurrent 25`, permanently, which is precisely the "plenty of headroom during an overload" reading the other module refuses to produce.

It compounds. `observability.py:20-22` lists voice admission among the things this module exists to fix — *"the pass-1 cap already tracks admitted/rejected/high water in memory, reachable only by reading `/voice/status` by hand."* It does not fix it. `voice/admission.py:164` increments `observability.voice_calls_admitted` inside the **voice** process, into a private `CollectorRegistry` (`observability.py:64`) that no HTTP server in that process ever renders — `voice/bot.py` has no `/metrics` route. **Every increment is written to a registry that is never scraped, and the series that is scraped is a constant zero.** The voice concurrency cap is unobservable in production, in both directions.

**The same shape applies to three more series, because only one of five processes serves `/metrics`.** `observability` is imported by exactly two modules, `main.py:39` and `voice/admission.py:164`. `worker.py`, `bot_worker.py` and `voice/workers/insurance.py` never call `setup_logging()` or `register_collectors()` and expose no port. So:

- **`circuit_breaker_state` reflects only the api process.** But `bot_worker` is the process that actually sends WhatsApp messages and calls Azure OpenAI. Its `whatsapp_meta` and `azure_openai` breakers can be wide open with zero signal on `/metrics`. The breaker you can see is the one least likely to have tripped.
- **`rate_limit_throttled`** reads a process-local `defaultdict` (`kb_rate_limit.py:31`). The `shared_counter_unavailable` alarm — whose whole purpose `kb_rate_limit.py:96-99` describes as *"that has to be visible in /metrics"* — is invisible whenever the degradation happens outside the api.
- **`kb_result_cache`** hit rate is reported for one of three independent 256-entry caches.

`job_queue_depth` is the exception and is correct, because it queries Postgres (`observability.py:238`) and is therefore deployment-wide no matter who scrapes it. That is the design to copy.

**Fix.** Port the `embedded_host_enabled()` guard verbatim from `voice_sandbox.py` into `_voice_samples` — emitting nothing beats emitting a constant zero for a saturation gauge. Then give the other four processes a scrape target: `prometheus_client.start_http_server(port, registry=observability.REGISTRY)` in each `main()`. `prometheus-client` is already a dependency and `REGISTRY` is already private and per-process, which is exactly what makes separate scrape targets safe.

---

## I17 — The breaker insight was applied to MinIO and not to Meta

`storage.py:160-165` explains which exceptions a circuit breaker must ignore:

> `A malformed storage_ref or an unconfigured deployment is a caller/config problem — counting those would trip the breaker and fail healthy traffic.`

and passes `ignore_exceptions=(ValueError,)` at `:169`. Correct, and precisely reasoned.

`whatsapp.py:72` and `:132` call `circuit_breaker.get_breaker("whatsapp_meta")` with **no** `ignore_exceptions`, so `CircuitBreaker.call` counts every `Exception` (`circuit_breaker.py:171-176`). And `_send_text_message_uncircuited` raises `ValueError` for every outcome it distinguishes: `whatsapp_not_configured` (`:88`), `whatsapp_missing_recipient` (`:91`), HTTP errors (`:116`) and network errors (`:118`).

So five sends in an unconfigured deployment — or five to a malformed phone number — open the `whatsapp_meta` circuit for `CIRCUIT_RESET_TIMEOUT_S`, 60 seconds by default, and fail healthy traffic to Meta. The same class of bug the MinIO comment describes, in the module next door, with the fix already written one file away. Because `get_breaker` applies tuning only on first creation (`:198-203`), the correction is a one-line keyword argument at both sites.

---

## I18 — Two job queues have no visibility timeout, no attempt cap and no dead-letter, because their table has no columns for them

The codebase runs **fifteen `FOR UPDATE SKIP LOCKED` claim sites**. Four are fully featured, and `bot_jobs.py` is the reference implementation: advisory-lock single-flight per conversation with a bounded skip-list retry whose reasoning occupies ten lines (`:193-203`), an attempt counter, exponential `run_after` backoff (`:352`), a `'dead'` state that **escalates to a human** (`:466-476`), `reclaim_stuck_jobs` as a real visibility timeout (`:140-183`), burst coalescing, and an idempotent `enqueue` using a savepoint plus SQLSTATE matching (`:96-130`). It is the best queue code in the repository by a wide margin.

Two queues have none of it, and cannot:

**`work_runtime_jobs`** — `alembic/versions/20260815_0077_phase4.py:65-83` defines no `attempt`, no `locked_at`, no `locked_by`, no `run_after`, and the status CHECK at `:70-72` has no `'dead'`. Its claim (`work_runtime/adapter_pg.py:170-175`) selects `status IN ('submitted','working')` and commits at `:185` *before* the handler runs, so a second drainer arriving after that commit sees `'working'`, holds no conflicting lock, and claims the same job. Including `'working'` is a defensible crash-recovery choice — with no reclaim function, it *is* the reclaim — but there is no attempt cap behind it, so a job that hard-crashes its worker is re-claimed forever. What saves it today is that all five handlers happen to be idempotent (`treatment/decisions.py:389` re-guards with `enacted IS FALSE ... FOR UPDATE SKIP LOCKED`; `clerk._run:158-166` handles the already-enacted case). That is a property of five handlers, not of the queue, and nothing tests it.

**`mcp_tasks`** claims `status='queued'` only — correct — but has **no reclaim anywhere**. A worker that dies between claim and finish leaves the row `'running'` permanently, with no timeout, no attempt counter and nothing that surfaces it. And `agent_core/mcp_http/tasks.py:146` records `error=type(exc).__name__`, **discarding the exception message**: a failed statement ticket records `"ValueError"` and nothing more.

Neither queue appears in `_JOB_QUEUES` (`observability.py:207`), which lists three of the fifteen claim sites. Neither does `webhook_deliveries`.

**And the scheduler has no lease.** `worker.py` is the only cron-like loop in the system, and its gates are module-level globals — `_last_tts_sync_day:37`, `_last_eval_day:333`, and six more. No advisory lock, no leader election. With one replica this is right and costs nothing. With two, the daily regression **and red-team suite** run twice, `_maybe_garden_kb_gaps` drafts every skill twice, and the TTS catalog syncs twice. The building block is already used five times elsewhere — `pg_advisory_xact_lock` in `db.py:704, 5745, 14380, 14820` and `pg_try_advisory_xact_lock` in `bot_jobs.py:229` — just never on the scheduler. `worker.py:88-90` shows the author reasoning carefully about *crash* resumption ("Stamp before the work, not after") and not about *replica* concurrency.

**Fix.** Add the four columns and `'dead'` to `work_runtime_jobs`, then migrate both thin queues onto `bot_jobs`'s primitives — but add `reclaim_stuck_jobs` **before** narrowing the `status IN ('submitted','working')` predicate, since that predicate is currently the only crash recovery `work_runtime_jobs` has. Widen `_JOB_QUEUES` to all fifteen. Put an advisory lease around each `_maybe_*` in `worker.py`.

---

## I19 — The one boundary with no tests and no metrics is the one on the audio path

Redis is used for exactly one thing: Pipecat's `RedisBus`, broadcasting role handoffs and activating the `insurance` sidecar. Two client constructions in the whole repository (`voice/mesh_bus.py:45`, `voice/workers/insurance.py:196`).

**First, a correction to my own brief.** I asked the analyst to work out what `--save "" --appendonly no` costs, on the assumption that something queued or cached in Redis was silently non-durable. Nothing is. `RedisBus` is pub/sub, which never persists regardless of AOF settings, and no code anywhere uses Redis as a queue or a cache. Disabling persistence is correct here, and the hypothesis was wrong.

The real problems are elsewhere.

**The publish sits on the audio path.** `voice/flows.py:659-663` puts `mesh_activate_insurance` in the `gated_upsell` node's **`pre_actions`** with `"respond_immediately": True`. Flows awaits pre-actions before the node speaks, so the handler at `voice/bot.py:1520` awaits `mesh_bus.activate_and_publish` → `bus.publish` → `redis.publish` → a network round trip, *before the bot says anything*. Neither client passes `socket_timeout` or `socket_connect_timeout`, so the bound is a library default — and which default is version-dependent in a way this repository does not pin down: `requirements.txt:14` pins `redis>=5.0,<6`, while the local `.venv` has 8.0.1 (whose default is 5s). The shipped container's value could not be verified from this tree. Best case is five seconds of dead air mid-call; the `try/except` at `:1528` catches the eventual error but cannot shorten the wait. The other call site is fine — `bot.py:1128` wraps it in `spawn_session_task`, off the mouth path.

**The advertised fallback does not cover the case that matters.** `mesh_bus.py:36-58` wraps `Redis.from_url` in a `try`, but `from_url` is lazy and does not connect, so the `except` catches only an **import** failure. With Redis unreachable, `_bus` is set to the `RedisBus` and never falls back to `_LocalBus` — every publish pays a connection attempt and lands in `logger.exception("mesh publish failed")`. The docstring promises *"otherwise an in-process async queue"*; that path is reached for a missing URL, never for a dead server. On the consumer side, if Redis dies after subscription, `_reader_loop`'s `async for ... in self._pubsub.listen()` raises and the task ends. No `health_check_interval`, no `retry_on_timeout`, no resubscribe — the container stays up under `restart: unless-stopped`, looks healthy, and is **silently deaf**.

**Redis is unauthenticated, and the deserializer imports modules named on the wire.** Pipecat's `JSONMessageSerializer` resolves a message's `__type__` — a fully-qualified dotted name taken from the payload — via `importlib.import_module`, with no allowlist. Anyone who can `PUBLISH bigbound.voice.mesh` makes the `voice_insurance` process import an arbitrary importable module, running its module-level side effects, and then construct an arbitrary model. Scoped honestly: compose binds Redis to `127.0.0.1:6379` and sets no `requirepass`, so this is lateral exposure on the compose network or the host, not internet-facing. The tell that a credential was expected is `voice/workers/insurance.py:198-212`, a `_redact_redis_url` helper written because *"REDIS_URL commonly carries redis://user:password@host — never log it raw."* The client would honour a password; nothing configures one.

**And this is the only boundary in the audit with zero tests and zero metrics.** `grep -rl mesh_bus tests/` returns nothing. No metric, no counter, no log line on a dropped message. Even the thin `mcp_tasks` queue has one of the two. That absence is a larger finding than any individual defect above, because every problem in this section would surface immediately if either existed.

**Fix.** Pass explicit `socket_timeout`, `socket_connect_timeout`, `health_check_interval=30` and `retry_on_timeout=True` at both construction sites — sub-second on the publisher, because it is on the audio path. Better still, move the `pre_action` publish off the transition path using the `spawn_session_task` pattern the same file already uses, since *any* timeout is dead air. Fall back to `_LocalBus` on the first publish failure, which is what the docstring already claims. Set `requirepass` and put the credential in `REDIS_URL` — the redaction helper for it is already written.

---
## I20 — Every mechanism for detecting a silent provider substitution exists; none of them reaches a durable record

The registry, the binder, the capability matrix and the key pool were built to stop one specific failure, and `voice/provider_bind.py:3-8` names it: *"an operator could pick Cartesia in the Agent Studio, hear the preview, publish it, and every real call still ran Azure."* The module fixes that. Its closing guarantee is what does not hold:

> `The fallback is not silent: every bind records what was asked for and what actually ran on `session.extra["providers"]`, so the transcript and the CRM record cannot claim a provider that never spoke.`

`provider_bind.py:124` writes it — `slots = session.extra.setdefault("providers", {})`. `session.extra` is a plain in-memory dataclass field (`voice/session.py:102`). **Nothing persists it.** `voice/persist.py` contains zero references to `.extra`; the only reads of the `"providers"` key anywhere are inside `provider_bind.py` itself and its test. `voice/crm_sink.py` *does* read `session.extra` — for `bot_id`, `direction` and `third_party` (`:284`, `:1537`) — which proves the plumbing to carry it into the CRM exists and was simply not used for this key.

So a call configured for Cartesia and voiced by Azure leaves exactly one ERROR log line and nothing durable. The transcript cannot claim the wrong provider, but only because it claims nothing at all. **The design is right, the fallback policy is right, and the half that makes the substitution auditable stops at the process boundary.**

Two more substitutions in the same family, neither surfaced:

**The preview endpoint reports the provider that did not speak.** `provider_tts.py:203-244` falls from Fish direct to OpenRouter on a credential fault — documented, deliberate, tested. But `synthesize` computes `provider` once at `:304` and returns it unchanged at `:350`, so `main.py:2996` sets `X-Tts-Provider: fish` on audio OpenRouter produced. `_cache_salt` (`:262-276`) then salts the cache with the *Fish* model id, so the OpenRouter take is stored under a Fish key. The only signal is a `logger.info` at `:225` — and see below.

**The locale map still fails open, in the exact place the factory says it was fixed.** `agent_core/providers/factory.py:3-7` opens by describing the bug: *"`voice/tuning_apply.py` resolved a locale with `.get(key, Language.EN_IN)` … an unmapped locale did not fail — it transcribed with an English-India recogniser and returned fluent nonsense that every downstream layer then scored as if it were the caller's words."* `voice/tuning_apply.py:70` is still `return mapping.get(key, Language.EN_IN)`. The map is now built from a shared registry and normalisation is case- and separator-insensitive — real improvements — but any tag outside that registry still silently becomes en-IN. The factory's half of the seam fails closed; this half does not. It is the highest-consequence substitution left in the system, because the failure mode is *plausible words* rather than an error.

**And `logger.info` from the API process is discarded.** `main.py` never calls `logging.basicConfig`, and `observability.setup_logging()` (`:470-486`) returns immediately unless JSON logs are enabled. Uvicorn configures its own `uvicorn*` loggers, not the root logger, so an application `logger.info` propagates to a root with no handler and falls to `logging.lastResort`, which emits at WARNING and above. INFO is dropped. That is the channel the Fish→OpenRouter fall-through uses to report itself. `logger.exception` and `logger.warning` still surface — including I1's one-per-request gateway line.

**Fix.** One write of `session.extra["providers"]` into the interaction record, using the path `crm_sink` already uses for three other keys. Recompute the returned `provider` from the adapter that actually produced audio. Make `normalize_language` raise or return a sentinel that `provider_bind` turns into `language_unsupported` plus a human handoff — which is what the multilingual design already specifies and what `factory.NoBindingError` already does on the other half of the same seam.

---

## I21 — Turning the gateway on dismantles the isolation the analysis lane was built to provide

`azure_openai.get_analysis_client`'s docstring (`:212-229`) records a measured incident: *"A WhatsApp turn spent 51 seconds inside `analyze_turn` — one attempt timing out at 20s, then retries — while the reply it was enriching took 1.8s."* The remedy was a separate deployment, an 8-second timeout, `max_retries=0`, its own semaphore (`AZURE_OPENAI_ANALYSIS_MAX_CONCURRENT=2`, acquire timeout 1s) and its own circuit breaker, so background analysis cannot delay or trip the circuit for the live conversational turn. It is one of the best-reasoned pieces of work in the repository.

`maybe_chat` is called at `azure_openai.py:619` — **before any of it.**

With `LLM_GATEWAY_ENABLED=true`, an analysis call gets: no `_analysis_slot`, so `AzureBusyError` never fires and `understanding.py:387`'s load-shedding branch becomes dead code; no `azure_openai_analysis` breaker; no separate concurrency bound; and the gateway's own retry loop, which is 3 attempts with **no sleep** at a flat 20-second timeout (I7). A caller passing a hard budget — `kb_plan.py:290` passes `timeout=budget` precisely so a live call can give up — gets up to three times that budget instead. **The exact failure the analysis client exists to prevent is reintroduced by a feature flag**, and the flag's name says nothing about it.

Two parameter defects compound it. `chat()` accepts `reasoning_effort` and never forwards it (I7), losing the measured 3.26s → 0.86s improvement `kb_plan.py:288` depends on. And `client.py:103` **always** sends `temperature`, while `azure_openai.py:594-596` deliberately omits it on reasoning deployments because those return 400. So a gateway fronting an o-series or GPT-5 deployment 400s on every request — and that 400 is swallowed by the fallback in I1 and served by Azure, so the gateway would appear to work while never actually being used, forever.

**Fix.** Move the cap check and the gateway call to positions where profile isolation still applies — or, more simply, adopt the recommendation below and stop treating the gateway as a layer above `azure_openai`.

### The framing question: should `llm_gateway` become the layer it claims to be?

No. `azure_openai.py` already is that layer, and it is better at it on every axis except two:

| capability | `llm_gateway/client.py` | `azure_openai.py` |
|---|---|---|
| business callers | 1 (inside the other one) | **16** |
| connection reuse | none — bare `httpx.post` per attempt | singleton + keep-alive |
| concurrency bound | none | two semaphores, bounded acquire, load-shed |
| circuit breaker | none | two, deliberately separate |
| backoff | **none** | SDK retry, plus caller budgets |
| profile isolation | 2 of 4 profiles unreachable | analysis lane with own client, timeout, retries, breaker |
| reasoning models | sends `temperature`, drops `reasoning_effort` | explicit override plus a deployment heuristic |
| tests | 2, both negative | 20+ indirect |

The gateway contributes exactly two things `azure_openai` lacks: a spend cap that I1 shows is non-functional, and canary model routing that cannot reach the profile its own promotion gate measures (I1). Promoting it would mean first giving it a pooled client, a breaker, backoff, reasoning-model handling and the analysis lane — which is reimplementing `azure_openai.py` inside it. By this report's own rule, that disqualifies it.

**Recommendation:** keep it as what it actually is — an APIM egress *adapter*, one deployment topology among several. Delete `PROFILES`, move the spend cap to `chat_with_tools` where it governs both paths, and fold canary routing into `azure_openai.get_chat_deployment()`, where it would reach all sixteen callers instead of one.

---

## I22 — The Fish promotion expired three days ago, and the fallback is on the same expired model

`agent_core/providers/fish_tts.py:45-60` is unusually careful documentation. It explains that the free tier is a *separate model id* rather than a discount, records a first-hand test — *"Verified 2026-08-22 on the same key: `s2.1-pro` → 402, `s2.1-pro-free` → 200"* — and states the migration: set `FISH_TTS_MODEL=s2.1-pro` and fund API credit. It also states the deadline: **free through 2026-08-31.**

Today is **2026-09-03**. Nothing has been flipped:

- `fish_tts.py:60` — `DEFAULT_MODEL = "s2.1-pro-free"`
- `openrouter_tts.py:40` — `DEFAULT_MODEL = "fish-audio/s2.1-pro-free:free"`
- `registry.py:441` — `model_id="fish-audio/s2.1-pro-free:free"`
- `.env.example:554, 574` ship both
- `tests/test_provider_registry_runtime.py` contains `test_fish_defaults_to_the_free_promo_model`, which *asserts* the expired id

The compounding detail is the one worth acting on: `provider_tts.py:203-244` falls from Fish direct to OpenRouter on a credential fault, and **both halves point at the same expired promotion.** So the documented fallback cannot rescue the primary. The expected sequence today is Fish 402 → fall through to OpenRouter → OpenRouter is also on the free id → `OpenRouterTTSError` → HTTP 422. A fallback whose failure mode is identical to the thing it backs up is not a fallback.

**Fix.** One environment variable and a funded balance, plus updating the test that pins the expired default. The migration path is already written in the docstring.

---

## I23 — One container's model usage is not metered at all

`voice/usage.py:1-8` states the gap it closed: *"Until now every production voice call was unbilled… This module closes that gap."* It does, for the `voice` container: Pipecat metrics flow through `voice/crm_sink.py:1362-1401` into `usage_meter`, and it correctly reads tokens off `.value`.

`voice/workers/insurance.py:42` constructs its own `KeepAliveAzureLLMService` in a separate container and attaches nothing. Searching that file for `usage`, `meter` or `observer` returns one unrelated comment. There is no `VoiceUsageMeter`, no metrics observer, no `enable_usage_metrics`. **Every token the insurance and upsell specialist burns is invisible to billing** — and that is a full conversational agent, not a helper call.

Structurally outside the meter as well, in smaller volume: `azure_openai.prewarm` (one chat plus one embedding, called from `bot_worker.py:205,231` and `voice/bot.py:2423`), `llm_pool._completion_ping` (`:141,151`), and `voice/spike.py:94,100`.

**Fix.** Attach the same `VoiceUsageMeter` the `voice` container already uses. It is one construction in `insurance.py`'s pipeline setup.

---
## Findings index

| # | Finding | Boundary | Severity |
|---|---|---|---|
| **I1** | The LLM spend cap reroutes around itself when it engages | AI / gateway | high |
| **I2** | The shared "is this production?" helper is pinned across one package; `main.py` is outside it | config / auth | high |
| **I3** | Two price books for the same token, ten times apart | billing | medium |
| **I4** | Every outbound hop is invisible except at the moment it dies | observability | high |
| **I5** | Two signature-verified webhooks 401 before their signature check | HTTP / auth | **critical** |
| **I6** | The SSRF guard resolves an address, discards it, connects by name | security | high |
| **I7** | The gateway answers a rate limit by tripling its request rate | HTTP | high |
| **I8** | Configuration documented, unread, and pinned by a test | config | medium |
| **I9** | Meta's envelope parsed in `db.py`; Twilio field names in routes | leakage | medium |
| **I10** | Row-level security is complete, correct, and switched off | database / security | **critical** |
| **I11** | One unique violation, three status codes; a bare catch in the money path | database | high |
| **I12** | One of four connection bounds is set; the budget holds only under compose | database | medium |
| **I13** | The `recordings` bucket is never created, so call audio lands in the KB bucket | storage | **critical** |
| **I14** | Transcripts are redacted for the model and not for disk | storage / privacy | **critical** |
| **I15** | MinIO has a 300s timeout; `delete_object` bypasses the breaker | storage | high |
| **I16** | `/metrics` publishes the exact number another module refuses to publish | observability | high |
| **I17** | The breaker insight was applied to MinIO and not to Meta | resilience | medium |
| **I18** | Two job queues have no visibility timeout, attempt cap or dead-letter | queue | high |
| **I19** | The one boundary with no tests and no metrics is on the audio path | queue / security | high |
| **I20** | Every mechanism for detecting a silent substitution exists; none reaches a durable record | AI / compliance | **critical** |
| **I21** | Turning the gateway on dismantles the analysis lane's isolation | AI | high |
| **I22** | The Fish promotion expired three days ago, and the fallback is on the same model | AI | **critical, dated** |
| **I23** | One container's model usage is not metered at all | AI / billing | medium |

---

## 3. Canonical boundary candidates

The brief asked for these specifically. One rule governs the list, and it is the rule this codebase keeps proving: **a shared layer is only worth creating if it is at least as capable as the best local implementation it replaces.** Several of the boundaries below already have a high-water mark in-tree; each candidate names the one it must match or beat. Where no shared layer is warranted, that is stated too.

### Tier 0 — the four fixes that need no new abstraction

Each is small, mechanical, and closes a live defect. Do these first; consolidating onto a broken layer propagates the break.

1. **Derive `_AUTH_EXEMPT_PREFIXES` from `authz.PUBLIC_ROUTES`, or assert the two agree in a test.** Three lines. Restores Twilio SMS delivery receipts and the bounce webhook. (**I5**)
2. **Create every bucket the code names, and make `bucket=` fail loudly instead of retrying elsewhere.** A `BUCKETS` registry iterated by `ensure_bucket`. Stops call audio landing in the KB bucket, stops the silent fallback, and stops recordings from opening the breaker KB uploads depend on — three consequences, one change. (**I13**)
3. **Route `export_transcript_json` and `call_export.build_bundle` through `transcript_view.redact_line`** — keeping *both* passes, since `pii_redact.redact_text` alone misses unformatted STT digit runs. (**I14**)
4. **`main.py` imports `env_utils.env_name()`**, and the offender scan in `tests/test_env_name_shared_helper.py` widens from `agent_core/` to the backend root. One line plus one path. (**I2**)

### Tier 1 — separate two meanings that currently share one channel

5. **Split gateway *failure* from gateway *cap breach* in `azure_openai.chat_with_tools`.** A failure should fall back to Azure — that is the kill-switch and it is correct. A cap breach should raise. Label `usage_meter`'s `source_ref` from what actually served the request rather than from the flag, so the fallback is visible. Then either route the voice hop through the gateway or delete `LLM_GATEWAY_CAP_VOICE_INR`, which today promises a control with no mechanism behind it. (**I1**, **I4**)

### Tier 2 — the shared clients the evidence supports

6. **One outbound HTTP client factory.** 16 files import `httpx`; 17 construct a client or call the module-level verbs. Nothing today gives them pooling, keep-alive, separated connect/read timeouts, or a metric. **High-water mark: `azure_speech.py`.** A shared factory must keep its module-level singleton behind a double-checked lock (`:53-63`), `Timeout(read, connect=…)` as two numbers rather than one, `Limits(max_connections, max_keepalive_connections)`, and the per-request override (`:531`, `:668`) that lets a caller tighten without building a second client. If it cannot express all four, `azure_speech` keeps its own.
7. **One retry policy object.** Five incompatible policies across six modules; only one has jitter and only one reads `Retry-After`. **High-water mark: `azure_speech._speech_call_with_retry` (`:378-410`)** — bounded attempts, `Retry-After` with a cap, full jitter, and `_SpeechRetryable`, which converts a retryable *response* into an *exception* so a breaker can count it. **It must also carry an idempotency flag**, or it would make `whatsapp_outbound.mark_failed_or_retry` strictly worse: that module deliberately dead-letters an ambiguous transport error rather than risking a second message to a borrower. (**I7**)
8. **An SSRF egress transport that pins the address it validated.** Two call sites, but this is the finding with a security consequence and the requirement is already written in-tree at `ops_screens.py:73-77`. Keep `resolve_public_host` verbatim — it is correct and well tested — add the pinning half and the IPv4-mapped-IPv6 case, and extend `tests/test_connector_ssrf_guard.py` rather than starting a new file. (**I6**)
9. **One Twilio client factory.** Three SDK clients from one credential pair, one of them (`scripts/set_twilio_voice_webhook.py:37`) with no timeout at all. Low risk, and it is the boundary where a duplicated credential is most likely to drift.
10. **One credential/header provider per TTS vendor.** Cartesia, Deepgram and ElevenLabs each have their auth headers rebuilt in both `provider_tts.py` and `provider_voice_sync.py`, at 60s and 30s respectively. Cartesia has already versioned its header once; a rename needs two edits today, and the preview would keep working while the catalog silently 401s.

### Tier 3 — the database layer

11. **One tenant predicate.** **High-water mark: `visibility.py:141-182`** — a constant SQL fragment with the scope entirely in bind parameters, a validated formatter, and a `params()` that resolves the actor from context *"so callers in `db` do not each have to remember to thread it through."* Its docstring makes the argument that has never been applied to tenancy: *"a predicate assembled from a role name is a predicate that can be assembled wrongly, and it defeats statement caching besides."* Evidence: 70 hand-written tenant predicates in four spellings against 364 `SELECT`s in `db.py` alone, with RLS off (**I10**) and no predicate at all on the KB vector path.
12. **One connection-acquisition helper.** 618 inline `engine.begin()`/`connect()` sites across 110 files, and **no session helper of any kind** — no `sessionmaker`, no contextmanager, no FastAPI dependency. The discipline is currently excellent and carried entirely by convention and three docstrings. `tests/conftest.py:11-59` already proves one indirection point is achievable: it monkeypatches a single attribute to control every call site. (**I12**)
13. **Extend `pg_errors.py` past 23505**, to 23503/23502/23514 and 40P01/40001, and make `_handle_write` or a global `SQLAlchemyError` handler the only path from a database exception to a status code. **High-water mark: `pg_errors.py` itself** — 29 lines, one decision, one place, with the drift it prevents named in the docstring. It is the right shape and covers one SQLSTATE. (**I11**)
14. **Add `connect_timeout` and `idle_in_transaction_session_timeout` to `connect_args`**, and one bounded contention retry modelled on `capture.py:1396-1421`. One of four connection bounds is currently set. (**I12**)
15. **One DSN resolver.** Three parsers with divergent `export `/quote handling. `env_loader.load_env` already implements the correct parse; the three private copies should call it.

### Tier 4 — queues and observability

16. **Promote `bot_jobs.py` to the canonical queue.** Fifteen `SKIP LOCKED` claim sites; `bot_jobs` is the only one with advisory single-flight, attempt caps, backoff, a real visibility timeout and a dead-letter that escalates to a human. Migrating `work_runtime_jobs` and `mcp_tasks` onto it requires a migration first — those tables have no `attempt`, `locked_at`, `locked_by` or `run_after` columns and no `'dead'` status. **Add `reclaim_stuck_jobs` before narrowing `work_runtime`'s `status IN ('submitted','working')` predicate**, since that predicate is currently its only crash recovery. (**I18**)
17. **Widen `_JOB_QUEUES` from 3 to all 15, gate `_voice_samples` on `embedded_host_enabled()`, and give the other four processes a scrape target.** **High-water mark: `observability.py` itself** — the `_SnapshotCollector` pull design is right and its cardinality rule is right; it is under-applied, not wrong. Nothing gets replaced; four processes start doing what one already does. (**I16**)
18. **Add outbound metrics at the client entry points.** `outbound_latency.labels(provider, operation)` and `outbound_errors.labels(provider, class)` — both bounded label sets, satisfying the existing cardinality rule. Twenty-one integrations currently have four circuit breakers between them and no latency or error series at all. This is the cheapest item here relative to what it buys, because the entry points it wraps are the ones Tier 2 creates. (**I4**)
19. **Bound and instrument the mesh bus**: explicit socket timeouts at both construction sites, `health_check_interval`, `retry_on_timeout`, fall back to `_LocalBus` on the first *publish* failure rather than only on import failure, move the `pre_action` publish off the audio path, and set `requirepass` — the redaction helper for the password is already written. **No high-water mark exists**: this is the only boundary in the audit with zero tests and zero metrics, which is a larger finding than any single defect in it. (**I19**)
20. **Advisory-lock leases around each `_maybe_*` in `worker.py`.** Costs nothing today at one replica; the day someone scales `worker` to 2 for throughput, the daily red-team suite runs twice. **High-water mark: `bot_jobs.claim_next_job:193-203`**, the repository's most careful use of advisory locks — read that comment before writing the lease.

### Tier 5 — the AI provider boundary

Candidate 21 is dated and belongs ahead of everything above it, including Tier 0.

21. **Flip the Fish model default off the expired promotion.** `FISH_TTS_MODEL=s2.1-pro` plus a funded balance, in `fish_tts.py:60`, `openrouter_tts.py:40`, `registry.py:441` and `.env.example:554,574` — and update `tests/test_provider_registry_runtime.py`, which currently asserts the expired id. The promotion ended three days ago and the fallback is on the same model, so there is no working path today. (**I22**)
22. **Persist `session.extra["providers"]`.** One write into the interaction record, along the path `voice/crm_sink.py` already uses for `bot_id`, `direction` and `third_party`. Until it exists, no artefact records that a call configured for one vendor was voiced by another, and `provider_bind`'s central promise is unbacked. Same fix shape for the preview endpoint: recompute the returned `provider` from the adapter that actually produced audio, rather than from the one that was asked. (**I20**)
23. **Make `normalize_language` fail closed.** `voice/tuning_apply.py:70` still returns `Language.EN_IN` for any unmapped tag — the exact bug `providers/factory.py:3-7` opens by describing. Raise, or return a sentinel `provider_bind` converts into `language_unsupported` plus a human handoff. This is the highest-consequence silent substitution left, because its failure mode is fluent words rather than an error. (**I20**)
24. **Attach a `VoiceUsageMeter` in `voice/workers/insurance.py`.** One construction. Today an entire conversational specialist runs unbilled. (**I23**)
25. **Shrink `llm_gateway` to what it is — an APIM egress adapter.** Delete `PROFILES`, move the spend cap into `chat_with_tools` where it governs both paths, and fold canary routing into `azure_openai.get_chat_deployment()` so it reaches all sixteen callers instead of one. Do **not** promote it to the shared LLM layer: `azure_openai.py` already is that layer and beats it on connection reuse, concurrency bounds, breakers, backoff, profile isolation, reasoning-model handling and tests. (**I1**, **I21**)
26. **Point `azure_speech.get_speech_key()` and `tts_catalog_sync` at `providers/pool.py`.** The pool already maps `azure` → `AZURE_SPEECH` specifically so the default provider has one, and it is the best-designed component in the provider package. Today the busiest Azure caller neither reads nor writes the pool health that `/providers/pools` reports.

### Where a shared layer should *not* go

- **`fish_tts.py` / `fish_service.py`** — a documented, deliberate split sharing `_TIMEOUT` and `build_payload`, so that auditioning a voice does not drag Pipecat into the API process. Leave it.
- **The two circuit breakers** — one wraps a callable in-process with a probe-generation state machine; the other gates a per-tenant row in Postgres and survives restart. They solve different problems and their tests cross-reference each other. The only defensible change is making `connectors/circuit.py`'s hardcoded `OPEN_AFTER=3`/`COOLDOWN_S=30` env-tunable to match its sibling.
- **The two Azure OpenAI clients** — a keep-alive async service for a live call and a sync tool loop are a real split. Share the *policy* (timeout bands, breaker name, meter, gateway), not the socket.
- **`whatsapp.py`'s error classifier** — vendor-specific by necessity, and its PII-stripping is load-bearing for what reaches a log or a database column. A generic error mapper must not flatten it.
- **Presigned URLs** — a deliberate non-recommendation. Nothing is served from object storage today, authorisation is centralised in a reviewable route table, and presigned URLs would move authorisation out of it. If recordings ever need serving, proxy through an authorised route; the prerequisites are candidates 2 and 3, not URL minting.
- **`adapter_temporal`** — 21 lines that raise `temporal_adapter_not_promoted` rather than degrading, with the promotion criterion recorded and a test pinning the fail-closed property. Keep it exactly as it is.

---
## 4. Verification of the prior report

The earlier `37-integration-boundaries.md` is preserved verbatim outside the repository. Its two weakest families — database and file/storage — were written by hand after its analysts aborted on a usage limit, and those are exactly the two re-run here with full budgets. This table records what happened to each of its load-bearing claims when checked first-hand.

| # | Prior claim | Verdict |
|---|---|---|
| 1 | `provider_bind` fail-open vs factory fail-closed is a **"policy contradiction"**; "Studio can show Cartesia while the call runs Azure" | **REFUTED as a contradiction — and the real defect is one neither report first saw.** The two-layer policy is deliberate and argued: strict where the binding decision is made, lenient where a live call would otherwise drop. But its closing guarantee — *"every bind records what was asked for and what actually ran on `session.extra["providers"]`"* — is **not implemented**: nothing persists that key. So the prior report's *conclusion* (a substitution can go unrecorded) is right for a reason it did not identify, and its *diagnosis* (a policy contradiction) is wrong. **I20**, §6 correction 5 |
| 2 | Dispute evidence / documents / export bundles mint `minio://` with no upload | **CONFIRMED (write path), CONSEQUENCE CORRECTED.** No download path exists to break — the read queries do not select `storage_ref`, `presign` appears zero times, and `get_bytes` has one caller. Dead metadata, not a broken download. Two worse things missed: the seeded `kb-sources` ref *is* dereferenced by re-indexing, and `db.py:5416` lets a client dictate the path its own comment says it must not. **I13** |
| 3 | Twilio is three clients | **CONFIRMED.** `twilio_sms.py:79`, `voice/twilio_ops.py:265`, and `scripts/set_twilio_voice_webhook.py:37` with no timeout |
| 4 | `whatsapp.py` uses `urllib.request`, 30s, twice | **CONFIRMED** (`:112`, `:191`) |
| 5 | Gateway retries 3× on 5xx with no sleep | **CONFIRMED**, and worse: 429 retries too, `Retry-After` is ignored, the verb is not idempotent, and `reasoning_effort` is silently dropped. **I7** |
| 6 | `maybe_chat` has one caller; the voice profile is unused | **CONFIRMED**, and extended: the cap breach falls through to uncapped Azure and the meter mislabels it. **I1** |
| 7 | One `create_engine`; `pool_pre_ping`, 5/10/1800 | **CONFIRMED.** Alembic's `NullPool` engine is a correct second one, worth recording |
| 8 | `connect_args` sets `statement_timeout` + tenant GUC as libpq startup params, so ROLLBACK cannot unset it | **CONFIRMED**, mechanism and all |
| 9 | No `connect_timeout`; `pool_timeout` default | **CONFIRMED and wider** — `idle_in_transaction_session_timeout` and `lock_timeout` are also unset. One of four bounds. **I12** |
| 10 | Three DSN parsers that may disagree | **CONFIRMED (three); consequence PARTLY.** Their hardcoded defaults *agree*; the divergence is in parsing — only `db.py` strips `export ` and quotes, so `export DATABASE_URL=…` silently sends seed and Alembic to localhost. Latent: `.env.example` uses neither form |
| 11 | `main.py` maps `IntegrityError`, workers do not | **PARTLY — the split is inside `main.py`.** `pg_errors` has 5 call sites, all workers, all correct. On the API: 82 routes → 409, ~34 → unhandled 500, 6 → 502, no global handler. **I11** |
| 12 | Raw `text()` everywhere is "the architecture, not a bypass" | **REFUTED as stated.** No ORM *and* no session helper of any kind; the tenant predicate is spelled four ways; and `visibility.py` demonstrates the canonical form the same codebase declined to apply to tenancy. A habit, not an architecture. **I10**, candidate 11 |
| 13 | Compose connection budget "≈25" | **CORRECTED to 28** — the header omits `voice_insurance` (2+1). And the budget holds only under compose: bare-metal via `run_stack.ps1` it is 75, the two paths agreeing at 15/process only by coincidence. **I12** |
| 14 | `storage.py` is the single MinIO client, no timeout | **CONFIRMED**, and quantified: **300s connect / 300s read** in the pinned `minio==7.2.20`, with `urllib3.Retry(total=5)` — up to ~30 minutes on a blackholed PUT. **I15** |
| 15 | `minioadmin` fallback is loopback-only | **CONFIRMED — and it is a positive.** Traced branch by branch; `minio.evil.com`, `127.0.0.1.evil.com` and `0.0.0.0` all correctly classify as remote |
| 16 | `delete_object` bypasses the breaker | **CONFIRMED**, and so do `ping` and `ensure_bucket`. `ping` bypassing is defensible; delete is not. **I15** |
| 17 | Recordings fall back from `bucket="recordings"` to the default bucket | **CONFIRMED, and far worse than stated** — the bucket is never created, so the fallback is not an edge case but the only outcome, on every recording. **I13** |
| 18 | `local://` refs are unreadable and lost on restart | **CONFIRMED**, plus a third scheme, `voicemail://`, and one consumer that does surface them (`live_qa/pack.py:255`) |
| 19 | Two TTS disk caches | **CONFIRMED** — character-identical eviction docstrings; `tts_preview_cache` is the strictly more capable of the two |
| 20 | Redis persistence disabled is a durability risk | **REFUTED** — the only Redis use is Pipecat pub/sub, which never persists. `--save "" --appendonly no` is correct here. (This was my hypothesis in the brief, not the prior report's.) |
| 21 | `circuit_breaker.py` may be unused; the two breakers may be duplication | **REFUTED on both counts** — 6 production call sites, and the split is justified (in-process callable wrapper vs per-tenant row in Postgres, with cross-referencing tests) |
| 22 | Job claim SQL is copy-pasted with stale windows of 180s vs 300s | **CONFIRMED in substance**, and the count is larger: 15 `SKIP LOCKED` sites, of which two have no visibility timeout, no attempt cap and no dead-letter at all. **I18** |

---

## 5. Checked and cleared

Hypotheses tested against source and abandoned. Each cost real effort and each is worth recording, because an audit that reports only what it found overstates its own hit rate.

| Hypothesis | Result |
|---|---|
| Sessions held open across external HTTP calls on the request path (classic pool exhaustion) | **Cleared.** All 618 `engine.begin()`/`connect()` blocks scanned for `await`, HTTP clients, sleeps, embed/LLM/storage calls and nested acquisition. Three hits, all false positives. The one real case (`kb_ingest.py:480`) is a background worker, off the request path. The rule is documented in three places |
| Multiple heads or branch points in 102 Alembic migrations | **Cleared.** 102 distinct revisions, one root, **one head**, no duplicates, no dangling `down_revision`, no merges. A linear walk reaches all 102 |
| Unguarded destructive DDL in migrations | **Cleared.** The one `TRUNCATE` match is inside a `RAISE EXCEPTION` *message*; that migration refuses to guess and aborts unless exactly one tenant exists. `CREATE INDEX CONCURRENTLY` is correctly inside `autocommit_block()` |
| Data migrations mixed into schema migrations | **Cleared.** Demo inserts sit behind `ALEMBIC_SEED_DEMO`, default off, *"so `alembic upgrade head` against a real customer DB never injects fake tenants"* |
| pgvector misconfigured or the bottleneck | **Cleared.** Two partial HNSW indexes with `vector_cosine_ops`, every query uses the matching `<=>` operator and orders by bare distance, the partial predicate is mirrored, and `hnsw.ef_search` is set per-query inside a savepoint so an unknown GUC cannot poison the transaction |
| Vendor endpoints hardcoded in business or route modules | **Cleared.** Eight vendor hostnames grepped; zero hits in `main.py`, `db.py` or any domain module |
| A second Postgres engine inside a runtime process | **Cleared.** One `create_engine` in application code; Alembic's `NullPool` engine and seed's raw psycopg are tools, correctly separate |
| A second MinIO client, or boto3 | **Cleared.** Exactly one `Minio(...)` construction repo-wide |
| Redis used as a domain cache or queue | **Cleared.** Pub/sub only; no GET/SET anywhere. `api` receives `REDIS_URL` and does not use it |
| Temp files created without cleanup | **Cleared.** Both TTS caches write to a unique temp then `os.replace`, with unlink-on-failure; the eval harness uses `mkdtemp` + `rmtree` |
| Object keys corrupted by Windows path separators | **Cleared in effect.** `storage._safe_segment` normalises backslashes, rescuing two callers that would otherwise break on Linux. Two key builders bypass it (`voice/recording.py:66`, `voice/persist.py:1324`) but `tenant_context._TENANT_RE` excludes both separators and interaction ids are server-generated — not currently exploitable, and named in **I13** as the paths to fix |
| Upload endpoints unbounded or holding a DB session | **Cleared.** `MAX_UPLOAD_BYTES` 25 MB enforced by `_read_upload_capped`; the KB path puts to MinIO *before* opening its transaction, with orphan compensation. (The whole file is buffered in memory — noted, not a finding at these caps) |
| Frontend calling Twilio/Meta/Azure directly | **Cleared.** Habibi's only HTTP client is `api/config.ts`, with one bypass for a sandbox export |
| `SOURCE_DB_ROOT` read by a process that does not mount it | **Cleared.** One reader, `scripts/kb_corpus_manifest.py` |
| `voice_session_store`'s filesystem fallback silently diverging between `api` and `voice` | **Cleared.** Fallback triggers only when a Postgres probe fails under `mode="auto"`, logged at ERROR; `mode="postgres"` raises rather than degrading; both processes share format and traversal guard. The compose comment describing it is accurate |
| The spend cap never accumulates because cost is always zero | **Cleared.** `usage_meter.chat_cost_inr` exists and falls back to a hardcoded price book, so it returns non-zero without pricing env. The cap is bypassable (**I1**), not inert |
| A synchronous provider call blocking the voice event loop | **Cleared.** Every sync provider call from `voice/` is wrapped in `asyncio.to_thread` — 36 sites, including understanding (`crm_sink.py:603`) and retrieval (`kb_enrich.py:360`). The gateway's blocking `httpx.post` is real but is never reached from a coroutine. Residual risk is thread-pool occupancy, not loop starvation |
| An AI-provider HTTP call relying on `httpx`'s 5s default | **Cleared.** Every one passes `timeout=` explicitly, including the MCP connectors. The hazard I briefed the analysts about does not occur on this surface |
| Provider specifics leaking into the turn engine | **Cleared.** `agent_core/turn.py` contains zero provider references. `main.py` handles providers at the right altitude — two typed exception handlers (`AzureBusyError`→503, `CircuitOpenError`→503) and no vendor status codes elsewhere. The leakage that does exist is confined to the TTS preview branch (**I9**) |
| The gateway's missing `rawMessage` breaking its callers | **Cleared.** `bot_runtime.py:976` reconstructs it with `.get(...) or {…}`; `sandbox_runtime.py:268` accepts either casing |

---

## 6. Corrections

Errors made during this audit and corrected before publication, plus corrections to the prior report and to my own briefing.

1. **I told all five analysts that `httpx` has a 5-second default timeout and that a missing `timeout=` is therefore a wrong value rather than an unbounded hang.** That is right for `httpx`, and I nearly generalised it. The MinIO SDK's default is **300 seconds**, and libpq's connect default is **unbounded** — so "no timeout set" means three different things in three places in this repository (**I12**, **I15**).
2. **I hypothesised that Redis persistence being disabled was a latent durability bug** and briefed the queue analyst to quantify it. Wrong: the only Redis use is pub/sub, which never persists. The setting is correct.
3. **I hypothesised the gateway spend cap was inert** because `_meter` computes cost inside a bare `except`. Wrong: `usage_meter.chat_cost_inr` exists at `:94` with a hardcoded default price book. The cap accumulates and is bypassed at a different point — a materially different finding, and only the second one is true.
4. **I asserted from memory that the API discards its own logs, cut it as unverified, and then had to put it back.** My first check found `observability.py:481` calling `basicConfig`, and I assumed uvicorn configures the root logger — so I removed the claim rather than publish something I could not stand behind. The provider analyst then established the mechanism precisely: that `basicConfig` is inside `setup_logging`, which returns early unless JSON logs are enabled, and uvicorn configures only its own `uvicorn*` loggers. An application `logger.info` therefore reaches a root logger with no handler and falls to `logging.lastResort`, which emits at WARNING and above. INFO is dropped; `warning` and `exception` are not. Restored in **I20**, where it is load-bearing: it is the channel the Fish→OpenRouter substitution uses to announce itself.
5. **I wrote `voice/provider_bind.py` up as an unqualified positive in §2** on the strength of its docstring's provenance guarantee, having verified the *policy* first-hand and taken the guarantee on trust. The provider analyst checked whether anything reads `session.extra["providers"]`. Nothing does. The §2 entry now says which half is delivered, and the finding is **I20**. This is the same error the prior report made in the opposite direction on the same module — it disbelieved the design and I over-believed the guarantee.
6. **I nearly reported `agent_core/vault/persist.py`'s PUT as missing a timeout** — a three-line grep window hid `timeout=10.0` on the fourth line. This became calibration #3 in every analyst brief.
7. **I nearly reported `fish_tts.py` / `fish_service.py` as a duplicate client for one vendor.** Reading the docstring, it is a deliberate split sharing `_TIMEOUT` and `build_payload`. It became the positive control in all five briefs — and the HTTP analyst independently flagged it as one.
8. **The prior report's "policy contradiction" between `providers/factory` and `voice/provider_bind`** is refuted; see §4, row 1. I checked this only because the calibration I had written for the analysts applied equally to me.
9. **The prior report's consequence for the phantom `minio://` refs** — 404s and empty downloads — is wrong; there is no download path at all. The write-path claim is confirmed and two worse adjacent findings were missed. §4, row 2.
10. **The compose connection budget is 28, not the "≈25" its own header states**, and the header omits `voice_insurance`, which the same file defines.
11. **My first attempt to inventory the backend used `grep -r` and `git ls-files | xargs grep`; both timed out at 120s** on `backend/.venv`, exactly as they do on `Habibi/node_modules`. Every analyst brief carried the scoping instruction as a result. One backgrounded run later completed and was used to cross-confirm two claims by a second method.
12. **A ripgrep pattern using look-ahead was rejected outright** (`rg` has no look-around). Noted in every brief.
13. **The queue analyst could not verify the shipped redis-py default socket timeout** — `requirements.txt` pins `>=5.0,<6` while the local `.venv` holds 8.0.1. It is reported as unverified rather than guessed (**I19**).

---

## Sources

Read first-hand for this report: `llm_gateway/client.py`, `llm_gateway/__init__.py`, `azure_openai.py` (600-745), `usage_meter.py` (33-120, 280-300), `env_utils.py`, `main.py` (200-300, 425-450, 585-600, 3380-3420, 3660-3690), `authz.py` (220-240), `rls.py` (1-30), `visibility.py` (130-182), `storage.py` (100-140, 230-245), `voice/recording.py` (60-95), `voice/provider_bind.py` (1-100), `voice_sandbox.py` (95-120), `observability.py` (1-60, 76-115, 190-215, 290-300, 470-486), `circuit_breaker.py` (1-60), `payment_events.py` (350-375), `ops_screens.py` (60-82), `webhooks_dispatch.py` (425-455), `agent_core/connectors/persist.py` (350-365), `agent_core/providers/fish_service.py` (1-45), `twilio_sms.py` (1-80), `whatsapp.py` (imports), `tests/test_env_name_shared_helper.py`, `tests/test_provider_preview_routing.py` (80-90), `docker-compose.yml`, `.env.example`, `requirements*.txt`.

Reproducible measurements: `wc -l` on the central modules (`db.py` 18,087; `main.py` 5,448; `voice/bot.py` 2,622); `grep -c` on `.env.example` (161 live keys, 81 commented); two independent sweeps for `httpx` importers (ripgrep tool and `grep -r`, agreeing at 16 files / 17 construction sites); two independent sweeps for RLS enablement (agreeing that only `rls.py` and its test contain the DDL, and only `scripts/rls.py` and the test import the module).

Five analysts: HTTP integration, database integration, AI provider, queue/cache, file/storage. Their inventories are the backbone of §1 and findings I1–I23; every claim this report headlines was re-read from source before publication, and the three that did not survive are recorded in §6.

Prior report preserved at `scratchpad/37-integration-boundaries.PRIOR.md` (31,234 bytes, 380 lines).
