# 19 — Identity, Authentication, Authorization

**Scope.** Identity resolution, authentication, authorization, session handling, privilege boundaries and object-level access control across `backend/` and `Habibi/`.

**Method.** Five analysts — authentication flow, authorization flow, route protection, frontend authorization, and token/session with object-level access — against ground truth I established first-hand: `authz.py` (895 lines), `actor_context.py` (230), `visibility.py` (183), `rls.py` (633), `tenant_context.py` (108), `request_context.py` (52), plus the auth middleware and route guard in `main.py`. Every headline claim below was re-read from source by me before publication; several analyst citations were corrected, and one of my own framings was wrong and is corrected in §13. **This audit was read-only. No product code was changed.**

**No roles were assumed.** Every role name here is quoted from `backend/seed_postgres.py`, `backend/authz.py` or `backend/visibility.py`. Where policy names a role that is never seeded, that is reported as dead policy rather than treated as real.

**One tenant is seeded.** As established in report 11, the schema seeds a single tenant. Findings whose impact is cross-tenant are therefore latent today and ranked as such; findings whose impact is *within* the tenant are live now. This report keeps the two apart deliberately.

---

## Verdict

**The authorization model here is the best-engineered subsystem in this repository. Its default configuration is off, and every control that would switch it on is keyed to one unvalidated string.**

That deserves saying before the defects. This system has a single canonical permission registry with a machine-checked, CI-enforced proof of totality; fail-closed grant resolution; a separate object-level visibility module using a constant, non-interpolated SQL predicate; three deliberately-separated identity ContextVars; a derived row-level-security plan; and seven dedicated security test files. The design is better than most production IAM layers. Across 318 routes there are **zero unregistered routes and zero stale policy rows**.

What is wrong is not the design:

1. **Every fail-closed control in the system is gated on `APP_ENV ∈ {"prod", "production"}`** (`main.py:204-205`, `actor_context.py:54-55`), with no allowlist of recognised environment names and no "unrecognised ⇒ treat as prod" fallback. `APP_ENV=staging` disables eight independent controls at once.
2. **The shipped configuration has authorization entirely off.** `backend/.env:145,149,154` — `APP_ENV=dev`, `API_KEY=` empty, `API_KEY_MAP=` empty. Authentication and authorization fail open on the *same* switch (`main.py:292`, `authz.py:639`), so there is no defence in depth between them, and object visibility follows both (`visibility.py:98-100`).
3. **The one action an operator takes to revoke a role's access restores that role's full default grant set** (P0-1).

Report 11 found a codebase with a contract and no mechanism to keep it true. This is the mirror image: **excellent mechanism, shipped switched off.**

---

## 1. The canonical authorization model

There is one, it is unambiguous, and it is `backend/authz.py`.

| Layer | Module | Question it answers | Status |
|---|---|---|---|
| Authentication | `actor_context.py` | Who is calling? | Static API key. **No OIDC, no JWT, no session** |
| Route authorization | `authz.py` | May they call this route? | Registry, CI-proven total over the API route table |
| Object visibility | `visibility.py` | Which customers may they see? | Reads only, ~3% of query sites; writes unscoped |
| Tenant isolation | `tenant_context.py` + `rls.py` | Which tenant's rows exist? | **Deliberately deferred, inert** |

**Route authorization** is one dict, `ROUTE_PERMISSIONS` (`authz.py:254-608`), mapping `(method, path_template) → permission id`, plus `PUBLIC_ROUTES` (`authz.py:213-248`). It is enforced by a single global dependency, `_authz_guard` (`main.py:507-551`), registered at app construction (`main.py:585`).

The design note at `authz.py:12-20` explains why this layer works where a per-route `Depends` would not:

> the policy is reviewable as a table — you can read what an Agent may do without grepping the endpoint bodies; `assert_registry_covers` can then prove the registry is *total* over the app's route table, so a new endpoint cannot ship ungated. A per-route `Depends` has no such property: forgetting one is silent.

**35 permissions** (`authz.py:106-140`), shaped `perm-<module>-<action>`.

**Roles.** `ROLE_DEFAULTS` (`authz.py:148-200`) defines six names — `admin`, `supervisor`, `agent`, `qa_reviewer`, `compliance_officer`, and `dpo` aliased to the last at `:200`. The seed creates **four** (`seed_postgres.py:663`):

```python
roles = [("role-agent", "Agent"), ("role-supervisor", "Supervisor"), ("role-admin", "Admin"), ("role-qa", "QA Reviewer")]
```

No SQL file inserts a role — `sql/01_identity.sql` creates the four tables (`:69`, `:78`, `:87`, `:94`) and nothing more; seeding is entirely Python. Every seeded name normalizes cleanly onto a `ROLE_DEFAULTS` entry, so no seeded role silently resolves to zero access. The inverse is dead policy — see H14.

**Grant resolution** (`authz.py:673-715`): `role_permissions` rows are authoritative when a role has any; a role with none falls back to `ROLE_DEFAULTS`; `perm-admin-write` or a role normalizing to `admin` short-circuits to `ALL_PERMISSIONS` (`:713-714`). Both caches fail closed on exception (`:730-735`, `:792-794`).

---

## 2. P0-1 — Revoking every permission from a role restores that role's full defaults

**The finding I would fix first. It is reachable by one click in the product's own UI, and the screen then displays the opposite of what is enforced.**

The resolver cannot distinguish "stripped of everything" from "never configured":

```python
# authz.py:702-709
granted: set[str] = set()
for role_id, explicit in explicit_by_role.items():
    if explicit:
        # The database has an opinion about this role — it is authoritative,
        # so a revoked grant stays revoked.
        granted |= explicit
    else:
        granted |= ROLE_DEFAULTS.get(role_names.get(role_id, ""), frozenset())
```

The join at `authz.py:686` is a `LEFT JOIN`, so a role with zero `role_permissions` rows still yields one row with `permission_id IS NULL`; `explicit` ends up the empty set and the `else` branch fires. **The comment three lines above is false in exactly this case.**

The chain, verified end to end:

| Step | Location | Behaviour |
|---|---|---|
| Operator unticks a role's last permission | `Habibi/src/routes/roles.tsx:26-34` | `next = current.filter(...)` → `[]`, sent as `permissionIds` |
| Route accepts it | `main.py:2857-2862` | `[]` is a valid list; only a non-list is rejected (422) |
| Rows deleted, none inserted | `db.py:496` | `DELETE FROM role_permissions WHERE role_id = :id` |
| Resolver falls back | `authz.py:709` | the role regains its full `ROLE_DEFAULTS` set |
| UI reports success | `roles.tsx:32` | `toast.success("Grants saved")` |
| UI then displays zero grants | `main.py:2828-2844`, `:2851` | `GET /roles` reads `role_permissions` rows only — an inner join |

**So the Roles screen shows a role holding nothing while the enforcement layer grants it everything in its default set.** For `supervisor` that is 23 permissions including `SUPERVISOR_WRITE` (call takeover), `CONSENT_WRITE`, `QA_WRITE` and `VOICE_OPERATE`. For `agent`, 13 — including `VOICE_OPERATE`, the right to telephone real borrowers.

The same fires with no intent to revoke: `db.py:478` filters the payload against `ALL_PERMISSIONS`, so a request whose permission ids are all misspelled also yields `wanted == []` and the same silent restoration.

**Why it survived review.** A test is named for exactly this property — `test_explicit_grant_beats_default_so_revocation_works` (`tests/test_authz.py:203`). It grants one permission, asserts a second is absent, and passes. It only ever exercises *partial* revocation. The case that inverts the result is the one an operator reaches for in an incident, and `db.replace_role_permissions` (`db.py:473-508`) has no test at all.

**And the one role this does not affect cannot be revoked either.** `authz.py:711-714` short-circuits on the role *name*, two lines after the comment establishing that explicit rows are authoritative "so a revoked grant stays revoked":

```python
if ADMIN_WRITE in granted or "admin" in set(role_names.values()):
    return ALL_PERMISSIONS
```

Stripping every permission row from `role-admin` therefore does not de-privilege its holders — and `db.py:494-495` re-appends `ADMIN_WRITE` on the way in besides. So the revocation path is broken in two different ways depending on which role you aim it at: for `admin`, revocation is impossible by design; for every other role, total revocation silently restores the defaults. **Neither path actually revokes.**

**Fix.** Distinguish "no rows" from "revoked to empty" — a sentinel row, or a `configured_at` column on `roles`. Then make `GET /roles` report *resolved* grants rather than raw rows, so the screen and the enforcer cannot disagree.

---

## 3. P0-2 — Every fail-closed control keys off one unvalidated string

`main.py:204-205`:

```python
_APP_ENV = (os.getenv("APP_ENV") or "dev").strip().lower()
_IS_PROD = _APP_ENV in {"prod", "production"}
```

Case and whitespace are handled. **No other environment name is.** `APP_ENV=staging`, `uat`, `prd`, `production-eu`, `live`, or unset turns off all of these at once:

| Control | Evidence | Effect when `APP_ENV` is not `prod`/`production` |
|---|---|---|
| Boot credential refusal | `main.py:431-433` | skipped |
| Per-request refusal with no key | `actor_context.py:203-205` | skipped → default actor |
| `ALLOW_ACTOR_HEADER` default | `actor_context.py:58-65` | defaults **True** — identity spoofing on |
| Twilio webhook signature | `main.py:3392`, `:3396` | **returns True** with no token, and with no signature |
| Voice WebSocket proxy secret | `main.py:3471-3479` | **returns True** with no secret |
| `validate_configured_actors` failure | `main.py:445-448` | downgraded to a warning |
| `_assert_hardening_gate` | `main.py:402-403` | skipped entirely |
| OpenAPI / docs publication | `main.py:588-590` | published |

Two verified verbatim:

```python
# main.py:3388-3396 — _twilio_signature_ok
    if not token:
        if _IS_PROD: ...
            return False
        return True                  # :3392  no token, non-prod → ACCEPT
    signature = (request.headers.get("x-twilio-signature") or "").strip()
    if not signature:
        return not _IS_PROD          # :3396  no signature, non-prod → ACCEPT
```

A UAT deployment holding real borrower data and labelled `APP_ENV=staging` is an open, spoofable, signature-free system, and nothing in the boot sequence says so. Every individual control is written correctly and does fail closed *in production*. The defect is that "production" is a string-equality test against a two-element set whose default is the unsafe value.

**Fix.** One line: `_IS_PROD = _APP_ENV not in {"dev", "test", "local"}`. That inverts the failure direction of every row in the table simultaneously.

---

## 4. P0-3 — `POST /a2a` bypasses authentication entirely and trusts client-supplied identity headers

`main.py:278-279`, evaluated *before* the exempt-prefix check:

```python
if request.method == "POST" and path == "/a2a":
    return await call_next(request)
```

It is also in `PUBLIC_ROUTES` (`authz.py:246`), so `_authz_guard` returns early too (`authz.py:827`). Both layers off. The route's own authentication resolves the caller from headers:

```python
# agent_core/a2a.py:23-32
def client_cert_dn(headers: dict[str, str]) -> str | None:
    verify = (headers.get("x-ssl-client-verify") or headers.get("ssl-client-verify") or "").strip().upper()
    if verify not in {"SUCCESS", "OK", "TRUE", "1", "YES"}:
        return None
    dn = (headers.get("x-ssl-client-dn") or headers.get("ssl-client-s-dn") or "").strip()
    return dn or None
```

`require_partner` (`a2a.py:39-70`) then matches on `cert_fingerprint OR cert_dn` (`:58`). The DN is not a secret — `GET /a2a/partners` returns `certDn` verbatim.

This is correct *if and only if* a reverse proxy terminates mTLS and strips inbound `X-SSL-Client-*`. **No such configuration exists in this repository** — a scoped search for `ssl-client` across `backend/` and `Habibi/` returns hits only in `a2a.py` itself. The module docstring states the intent ("A bearer token without a client certificate is not enough") and the intent is sound; the enforcement lives in infrastructure that is not in the repo and cannot be verified here.

**Ranked P0 pending infrastructure evidence.** If an ingress genuinely strips those headers this drops to P1 — still reachable by anything inside the network able to address the app port directly, which in a Kubernetes deployment is every pod. The same header trick satisfies the auth-exempt `GET /.well-known/agent-card.json`.

---

## 5. The map

The brief asked for **login → identity → token/session → frontend state → API request → authorization check → resource access**.

**Login.** There is none. Greps across `Habibi/src/` for `useAuth`, `AuthContext`, `msal`, `auth0`, `firebase`, `clerk`, `signIn`, `logout` return no auth code, and `beforeLoad` appears zero times in any route. The app assumes *whoever can load the page is authorized*. `Habibi/src/api/me.ts:1-9` states the plan — "Real authentication replaces the server side in Phase 5 (OIDC)". Phase 5 has not landed.

**Identity.** A build-time constant. `Habibi/src/api/config.ts:38` reads `VITE_API_KEY`, `:45` reads `VITE_ACTOR_USER_ID`, and `authHeaders()` attaches both to every request (`:52-53`). Vite inlines `VITE_*` literals into the bundle, so both ship to every browser. `Habibi/.env.example:6-8` warns about exactly this — "never put a shared backend secret here… treat it as a browser-visible demo key only" — and then `:11` gives the example value `VITE_ACTOR_USER_ID=priya-nair`, who is the seeded administrator (`seed_postgres.py:690-691`).

**Token / session.** None. No JWT, no cookie, no expiry, no refresh. The credential is a static string. See §9.

**Frontend state.** The frontend is never told who the user is beyond a display name. `MeResponse` (`schemas.py:526-537`) is `id, name, kind, team, status, tenantId` with `extra="forbid"` — **no roles, no permissions**. Consequently there are zero role-based UI gates.

**API request → authorization check.** `ApiKeyMiddleware` (`main.py:260-318`) resolves the actor and binds it to `request.state.actor_user_id` (`:309`). `_authz_guard` (`main.py:507-551`) reads `scope["route"].path` — the template, so `{customer_id}` routes match the registry — and calls `authz.check`. It deliberately reads `conn.state.actor_user_id` rather than `actor_context.get_actor_user_id()`, and says why (`main.py:539-541`): the ContextVar falls back to the process default, and "that would hand an unauthenticated caller the default user's grants." A correct and non-obvious call.

**Resource access.** `visibility.params()` supplies bind parameters for a constant predicate substituted by `db._sql()` — into 14 of roughly 491 query sites. See §8.

---

## 6. Authentication

**Mechanism.** `X-API-Key`, falling back to `Authorization: Bearer` (`main.py:283-287`). No query string, no cookie. Comparison is `secrets.compare_digest` throughout (`actor_context.py:172-175`). Resolution order (`actor_context.py:178-231`): `API_KEY_MAP` JSON `{secret: users.id}`, then shared `API_KEY` plus optional `X-Actor-User-Id`, then the `ACTOR_USER_ID` env default.

**H1 (P1) — shared key plus a header is complete identity assumption.** `_resolve_shared_key_actor` (`actor_context.py:221-226`) validates the claimed identity only with `_user_exists`. That header value becomes `request.state.actor_user_id`, which `_authz_guard` feeds straight to `authz.check` (`main.py:542-544`). Pick an administrator's `users.id` — enumerable via `GET /staff` — and you hold `ALL_PERMISSIONS`. Guarded only by `_allow_actor_header()` defaulting off in prod (`actor_context.py:58-65`), which P0-2 shows is one environment name away from being lost. CI itself runs with `ALLOW_ACTOR_HEADER: "true"` (`.github/workflows/backend-pytest.yml:40`).

Aggravating: when `API_KEY_MAP` *is* configured — the per-user, preferred mode — a legacy `API_KEY` left set alongside it still falls through to the shared-key path (`actor_context.py:189-199`), so the good configuration is bypassable by the old one.

**H2 (P1) — Twilio webhooks are auth-exempt *and* signature-optional outside production.** Four `/twilio/voice/*` paths sit in `_AUTH_EXEMPT_PREFIXES` (`main.py:243-247`) on the stated grounds that they carry their own signature check. Outside production that check accepts anything (`main.py:3392`, `:3396`). `POST /twilio/voice/call-status` drives the `call_attempts` state machine, so forged answer rates, durations and outcomes flow into the treatment engine's inputs. This is the "public route that does not actually verify a signature" case, bounded to non-prod by `_IS_PROD` — which is P0-2's point.

**H3 (P1) — no credential lifecycle of any kind.** No rotation: `API_KEY_MAP` is parsed once and cached for process lifetime, and `reload_api_key_map` (`actor_context.py:68-73`) is called only from tests. No expiry — the map is a bare `{secret: user_id}` dict with no metadata. No revocation list; revoking one user means editing env and restarting the whole API. No per-key audit — audit rows carry only the resolved `users.id`, so two keys mapping to one user, or all holders of the shared key, are permanently indistinguishable. **And no deactivation concept**: `db.user_exists` (`db.py:439`) is `SELECT id FROM users WHERE id = :id`, consulting no `active`, `status` or `deleted_at` column.

**H4 (P2) — cache invalidation exists and is never called.** `actor_context.invalidate_user_exists_cache` (`:121-127`, docstring "call after user writes") and `authz.invalidate_permission_cache` (`authz.py:652-666`) have no non-test callers. `db.replace_role_permissions` commits and returns without invalidating either. Both caches are TTL-only at 30s, per worker process. An emergency revocation is therefore deferred up to 30 seconds on every process independently, with no way to force it.

---

## 7. Route protection

**The registry is total over the API route table, the proof runs in CI, and there are zero unregistered routes. Four FastAPI-generated documentation routes sit outside both the guard and the proof.**

The arithmetic closes exactly:

| | count |
|---|---|
| `@app.<method>` decorators in `main.py` (AST-parsed) | 314 |
| Unique `(METHOD, path)` | 314 — **zero duplicates** |
| Conditionally registered (`voice/host.py:179-181`, `VOICE_EMBEDDED_HOST`) | 4 |
| **Total route table** | **318** |
| `PUBLIC_ROUTES` | 26 |
| `ROUTE_PERMISSIONS` | 292 |
| **Registry total** | **318** |
| Routes in neither registry | **0** |
| Registry rows matching no route | **0** (the 4 flagged are the conditional ones, whitelisted at `tests/test_authz.py:49-54`) |
| `app.mount` / `StaticFiles` / `include_router` / `add_api_route` | **0** |

Three mechanisms hold this, all real:

1. `check()` denies any route absent from both dicts (`authz.py:829-834`) — `PermissionDenied("unregistered_route")`. A new endpoint nobody classified is *unreachable*, not open.
2. `assert_registry_covers` (`authz.py:879-895`) turns that runtime denial into a build failure, driven by `test_registry_covers_every_route` (`tests/test_authz.py:38-40`).
3. A second test closes the reverse direction — `test_registry_has_no_entries_for_routes_that_do_not_exist` (`tests/test_authz.py:43-61`) — so stale policy rows that protect nothing also fail the build.

**Unlike the contract gate in report 11, this one is not defeated by path filtering.** `.github/workflows/backend-pytest.yml` is `paths:`-filtered to `backend/**` (`:3-11`), and `authz.py`, `main.py` and `tests/test_authz.py` all live there. Any change that could break coverage runs the test that catches it. **This is the single strongest control in the audit.**

**H15 (P1) — `/docs`, `/redoc`, `/openapi.json` are outside both the guard and the proof.** FastAPI registers its own documentation routes with `self.add_route(...)`, which produces a plain `starlette.routing.Route` rather than an `APIRoute`. Two consequences: the global `dependencies=[Depends(_authz_guard)]` (`main.py:585`) is injected by `add_api_route` and therefore does not apply to them; and `_app_routes()` (`tests/test_authz.py:29-35`) filters to `APIRoute`/`APIWebSocketRoute`, so `assert_registry_covers` never sees them. There is no `("GET", "/openapi.json")` row anywhere in `authz.py`, and nothing flags its absence. They *are* behind `ApiKeyMiddleware` — deliberately, per the comment at `main.py:231-232` — but that is authentication only. **Any key holder, including an actor with no roles at all, can read the complete API schema.** Disabled only under `_IS_PROD` (`main.py:588-590`), which per P0-2 defaults to False.

This qualifies the totality claim precisely: the proof is total over `APIRoute` and `APIWebSocketRoute`, not over `app.routes`.

**H16 (P1) — WebSocket routes receive no registry authorization, and their fallback fails open outside production.** `_authz_guard` returns early on non-HTTP scopes (`main.py:533-534`), so `authz.check` is never called with method `"WS"`. FastAPI *does* attach the dependency to websockets; the guard runs and then declines. The `("WS", …)` rows in `PUBLIC_ROUTES` (`authz.py:237-238`) are therefore decorative at runtime and load-bearing only in CI, where `_app_routes()` emits them and their removal would fail the coverage test.

The actual control is `_voice_ws_upgrade_authorized` (`main.py:3442-3481`), requiring `VOICE_WS_PROXY_SECRET` — **and it fails closed only under `_IS_PROD`**; its final statement is `return True` (`main.py:3479`). So in any deployment that has not explicitly set `APP_ENV=production`, `/ws` and `/ws/{proxy_secret}` accept an upgrade from anyone who knows the URL, with no secret and no key. With `VOICE_EMBEDDED_HOST=true` that runs a live in-process call session on the regulated voice channel.

The early return is nonetheless deliberate and well documented (`main.py:520-532`): the parameter is `HTTPConnection` rather than `Request` because, annotated `Request`, the dependency solver raised `TypeError` and rejected the upgrade with a 500 — "Twilio's Media Stream never connected, the customer heard silence, and every status callback still reported a healthy call." And `tests/test_voice_ws_authz.py` pins the route list so a third socket cannot inherit the carve-out silently. That control is real and works.

**The exempt list is prefix-matched but segment-bounded** (`main.py:280`): `path == p or path.startswith(p + "/")`. A prefix cannot bleed into a sibling — `/ws` does not exempt `/ws-admin`, and `/metrics` is not exempt at all (permission-gated on `OBSERVABILITY_READ`, `authz.py:581`). The list carries a scar in its comments (`main.py:240-242`): a blanket `/twilio` prefix once left `POST /twilio/voice/outbound` open to the internet — "anyone could dial arbitrary PSTN numbers on our account." It is now four exact paths, regression-pinned in `tests/test_production_hardening.py`.

**H5 (P2) — the two exempt lists are the same policy written twice, and they disagree.** `POST /twilio/sms/status` and `POST /webhooks/collections/payment-events` are in `authz.PUBLIC_ROUTES` (`authz.py:229`, `:233`) — declared "the signature check is the authentication" — but absent from `_AUTH_EXEMPT_PREFIXES` (`main.py:233-257`). Once `API_KEY` is set they 401 in the middleware before the HMAC ever runs. Silent data loss on delivery receipts, not a bypass; no test asserts the two lists agree.

---

## 8. Object-level authorization

**Partially implemented, mostly not reached, and globally disabled in the shipped configuration.**

Permissions answer "may you read customers". `visibility.py` is the only thing that answers "may you read *this* customer", and it resolves an actor to one of three scopes (`:61-63`): `ALL` for `admin`, `qa_reviewer`, `compliance_officer`, `dpo` (`:67`); `TEAM` for `supervisor`, `manager` (`:68`); `OWN` for everyone else **and for any unrecognised role** (`:127-129`) — unknown means most restricted, the right direction.

The predicate (`visibility.py:148-156`) is a constant string with scope carried entirely in bind parameters. The reasoning at `:139-144` is exactly right: "a predicate assembled from a role name is a predicate that can be assembled wrongly." `vis_all` collapses it to constant true for unscoped actors, so "admin" and "feature disabled" take the identical code path. The team rule is subtler than it looks and the module says so (`:22-26`): supervisors match through `teams.supervisor_user_id`, not shared `team_id`, because reading it the obvious way "would have shown a supervisor their fellow supervisors' customers and hidden their actual reports'."

**H6 (P1) — the mechanism is fail-open by construction, and reaches ~3% of query sites.** `db._sql()` (`db.py:241-255`) substitutes the predicate for a `/*VISIBILITY*/` marker. A query that forgets the marker keeps it as an inert SQL comment and is therefore **unscoped**. The docstring is candid (`:248-253`): "fail-open, which is the wrong direction. That is deliberately not defended against here… What catches it is `tests/test_object_visibility.py`."

Measured:

| | count |
|---|---|
| `_sql(` call sites in `db.py` | 13 |
| Direct `visibility.predicate()` use | 1 — `db.py:978`, `_base_customer_row` |
| **Total scoped query sites** | **14** |
| `.execute(` call sites in `db.py` | ~491 |
| Files in `backend/` that import `visibility` | **1** — `db.py:21` |

So `main.py`, `ops_screens.py`, `followups_db.py`, `payment_events.py`, `work_runtime/`, `agent_core/` and `voice/` contain no object-level scoping at all, and every one of the 14 scoped sites is a *list* query — no by-id fetch is scoped except `get_customer`, which shares `_base_customer_row`.

**H7 (P1) — writes are not object-scoped.** `visibility.py:42-49` states it: "This scopes what an actor can *see*. The by-id write guards in `db` stay at tenant granularity." Those guards are `_assert_tenant_owns` (`db.py:263-290`), which verifies tenancy and nothing more.

| Endpoint | Enforcement | Verdict |
|---|---|---|
| `GET /customers/{id}`, `/insights` | tenant **+ visibility** (`db.py:978`) | **Clean** when enforcement is on |
| `POST /handoff/{id}/claim` | tenant + `to_user_id != actor` + queue check (`db.py:4576,4598,4603`) | **Clean — best-guarded route found.** An agent cannot steal a claimed handoff |
| `GET /conversations`, `/conversations/{id}` | `_conversation_base_rows` (`db.py:8994`) builds its `WHERE` from `conversation_id` and `updated_after` **only** | **No tenant filter, no scope** — the default screen |
| `GET /interactions/{id}/export` | `voice/call_export.py:50-59` — `WHERE i.id = :id` | Unscoped; richest PII object in the product |
| `GET /interactions/{id}/trace`, `/cost` | existence check only | Unscoped |
| `GET /sandbox/runs/{id}`, `/eval/reports/{id}` | `WHERE id = :id` | Unscoped |
| `PATCH /promises|disputes|callbacks|document-requests/{id}` | `_assert_tenant_owns` — tenant only | **Write IDOR within the tenant** |

The write band is documented rather than accidental — narrowing it "needs product answers this module should not invent: whether an agent may claim an unassigned account, whether `takeover_conversation` should refuse a customer assigned to someone else… over-tightening a write path breaks a workflow silently, and guessing at it would be worse than the gap." That is an honest engineering note. The residual risk is still real: any agent holding `collections:write` can mark another agent's promise kept, suppressing that customer from the queue.

`_assert_tenant_owns` raises `KeyError` → 404 rather than 403, deliberately (`db.py:272-275`): "answering 'that exists but is not yours' confirms the id." Correct.

**The missing-tenant cases are latent, not live** — one tenant is seeded, so nothing crosses a tenant boundary today. What *is* live is the missing visibility scoping: within the single tenant, every agent can list every conversation and export every call recording. And note that `tests/test_inbox_outbound_visibility.py`, despite its name, tests message *delivery* state, not access control — so a reader looking for inbox scoping coverage will find a file that appears to provide it and does not.

**H17 (P1) — client-settable audit attribution.** `db.py:8339`:

```python
handler_user_id = payload.get("handlerUserId") or (_actor_user_id() if handler_kind == "human" else None)
```

`POST /interactions` accepts `handlerUserId` from the request body unvalidated. `handler_user_id` is what QA scorecards, coaching actions and `workspace_summary` aggregate on, so an agent can post a call attributed to a colleague and move that colleague's scorecard. `db.py:5320` does the same for a dispute's `assigneeUserId`, without even an existence check.

**Tenant isolation is inert, and the codebase says so.** `db.py:277-280`: "The structural fix is the row-level security in `rls.py`… but that is inert until the application stops connecting as a superuser."

`rls.py` is 633 lines of real machinery — `plan()` derives ~90 tenant policies from the FK graph in two passes, `enable()` applies `FORCE ROW LEVEL SECURITY` (`:477-480`) and verifies row counts inside the transaction, `role_bypasses_rls()` refuses to install for a BYPASSRLS role, `provision_role()` creates a `NOSUPERUSER NOBYPASSRLS` role. **Nothing calls it.** `rls.apply`/`rls.enable` are invoked only from `scripts/rls.py` (a manual CLI) and `tests/test_rls.py`. No `CREATE POLICY` or `ENABLE ROW LEVEL SECURITY` appears in any of the 27 `sql/*.sql` files or 65+ Alembic migrations. The app connects as `collections`, the Postgres image's bootstrap superuser — for which `rls.enable()` would raise `EnableRefused`. That connection role is not merely a compose default: `db.py:39` hardcodes it as `DEFAULT_DATABASE_URL`, so **no configuration path in this repository connects as a non-bypassing role.**

**This is deferred, not overlooked** — and my first framing had it as the latter, which was wrong. `main.py:388-397` names "RLS tenant isolation" first in `_DEFERRED_HARDENING_CONTROLS`, and `_assert_hardening_gate` (`main.py:400-418`) **refuses to boot in production** while those controls are inactive. The reduced finding is narrow: the escape hatch `ALLOW_UNHARDENED_PRODUCTION=1` downgrades that refusal to a log line (`main.py:405-412`), and activation is a manual four-step CLI sequence with no automation and no drift check. A control requiring an operator to remember four commands in order is a control that will be half-applied.

---

## 9. Sessions, tokens, and credential handling

**There is no session layer.** No JWT, no cookie, no `SessionMiddleware`, no `set_cookie`, no expiry, no refresh. A scoped grep for `jwt`, `PyJWT`, `jose`, `itsdangerous`, `SessionMiddleware`, `set_cookie`, `refresh_token` across `backend/**/*.py` returns three hits, all comments — `actor_context.py:3` ("Until OIDC/JWT lands"), `db.py:423` ("Phase 5 replaces resolution with JWT `sub`"), `tenant_context.py:12`.

`requirements.txt` settles it at the dependency level: no PyJWT, no python-jose, no authlib, no itsdangerous, no passlib, no session middleware. This is not dormant code — the capability was never installed.

Consequently: **there are no stale sessions, because there are no sessions** — and equally no logout, no revocation, no concurrent-session visibility, and no way to end access without a restart.

**H8 (P1) — the process-default actor is an administrator, so background writes run as superuser and are filed as a named human's manual actions.** This is the audit-integrity finding.

`actor_context.py:35-42` defaults to `priya-nair`; `backend/.env:157` sets it explicitly; `seed_postgres.py:690-691` grants that exact user `role-admin`. `_authz_guard` is hardened against this for HTTP (`main.py:542`), but `db._actor_user_id()` (`db.py:419-430`) is not — it falls straight through to the default. `actor_context.set_actor_user_id` is called in exactly one place in the whole backend: `main.py:310`, inside the middleware. The four worker services in `backend/docker-compose.yml` never touch it.

And the audit writer hardcodes the actor *kind*:

```sql
-- db.py:642-659, _activity()
INSERT INTO activity_events
  (id, tenant_id, entity_type, entity_id, actor_kind, actor_user_id, kind, label, note, payload)
VALUES
  (:id, :tenant_id, :entity_type, :entity_id, 'human', :actor_user_id, ...)
```

`'human'` is a literal at `db.py:649`; `:actor_user_id` is `_actor_user_id()` at `db.py:658`. **There is no `actor_kind='system'` path anywhere.** So an unattended follow-up sweep, a bot's own outbound WhatsApp reply, and a payment processor's bounce callback are each recorded as *a human named Priya Nair* performing them. `visibility.params()` (`visibility.py:172-176`) resolves those same paths to scope `ALL`.

This is the same family as the `requestedVia` fabrication in report 11: a field that exists to answer *who did this* answering with a name that is not true. Here it is worse in one respect — the wrongness is unfalsifiable from the data alone, because the honest value is not representable.

**H9 (P2) — a second, better-designed credential system, mintable from the weaker one.** MCP HTTP (`agent_core/mcp_http/auth.py`) stores keys as SHA-256 digests, honours `revoked_at`, records `last_used_at`, scopes each key against a `KNOWN_SCOPES` allowlist, default-denies unknown tools, and binds `127.0.0.1`. It has every lifecycle property the primary system lacks, and it runs as a genuinely separate process ("never mounted on FastAPI"). Two caveats: `/mcp/keys` mint/rotate/revoke (`main.py:2483-2512`) is gated only on `INTEGRATIONS_WRITE`, so compromising the weaker system mints credentials in the stronger one; and **an MCP key binds a tenant and a scope list but never a user**, so every CRM read it drives resolves `db._actor_user_id()` to `priya-nair` and therefore to visibility scope `ALL`. A key nominally scoped to `crm.read` reads the entire portfolio. The MCP design is nonetheless where the primary auth layer should end up.

**H10 (P2) — two non-constant-time comparisons.** `main.py:4595` uses `==` on the WhatsApp `hub.verify_token` (low impact — it only echoes `hub.challenge`), and `_voice_ws_secrets_equal` (`main.py:3414-3417`) returns early on length mismatch, leaking the proxy secret's length before `compare_digest`. Every other secret comparison in the auth surface is constant-time.

**H18 (P2, documented tradeoff) — webhook signing is keyed with the stored digest.** `webhooks_dispatch.py:105-111` signs with `hmac.new(secret_hash, ...)`. The module explains why (`:26-31`): the plaintext endpoint secret is deliberately never persisted — rotation returns it once as `secretOnce` and stores only `sha256(secret)` — so the receiver holds the plaintext and derives the key to verify. That genuinely keeps the tenant's secret out of our database. What it does *not* buy is protection against a database reader: the stored value is a valid signing key, so read access to `webhook_endpoints` still yields forgery capability. Recorded so the limit of the property is explicit, not as an oversight — the reasoning is sound and written down.

**H19 (P2) — `GET /pay/{token}` renders expired intents.** Token entropy is sound (`secrets.token_urlsafe(24)`, 192 bits, `promise_fulfillment.py:271`) and completion is single-use and expiry-checked (`payments.py:149-162`). But the GET performs no `expires_at` check (`main.py:786-792`), so customer name, account and amount stay publicly retrievable indefinitely on an unauthenticated, unrate-limited route.

---

## 10. Frontend authorization

**No authorization decision in this product is made in the browser** — because the browser is never given the inputs to make one. `MeResponse` (`schemas.py:526-537`) carries no roles and no permissions, and greps across `Habibi/src/` for `isAdmin`, `hasPermission`, `hasRole`, `me.role` return only the `/roles` editing screen itself. Every `disabled=` in the codebase keys off domain state, never identity. All 35 permissions are enforced exclusively server-side. **The "frontend-only authorization" category the brief asked me to hunt is empty, and that is genuinely good news.**

The exposure runs the other way, and it is worse: the browser cannot weaken a permission check, but it *chooses which principal the check runs against* (`config.ts:45,53`).

**H11 (P1) — eleven invisible gates.** The sidebar (`Habibi/src/components/shell/Sidebar.tsx:57-104`) is a static array rendered in full to every viewer, filtered only by the search box. A `qa_reviewer` sees and can open Billing, Consent & DND, Redaction & export, Call sandbox and Roles & access, and 403s on each. Worst of these: `/roles` renders the complete permission catalog and every current grant — because `GET /roles` is only `BOT_READ` (`authz.py:360`) while its sibling write is `ADMIN_WRITE` (`:361`) — then invites the user to tick checkboxes the server will refuse. The full RBAC matrix is readable by any supervisor, which is useful reconnaissance for H1.

**H12 (P2) — a 403 is indistinguishable from a network failure.** `ApiError` (`config.ts:130-142`) carries `status` but exposes only `isNotFound`. Nothing in `Habibi/src/` inspects `status` for 401 or 403. A permission denial surfaces as a raw backend `detail` string in a toast or a red div, identical to an outage. There is no re-authenticate path, because there is nothing to re-authenticate to.

**H13 (P2) — one raw `fetch` outside the wrapper**, at `Habibi/src/routes/sandbox.lazy.tsx:432`, targeting a route requiring `INTERACTIONS_READ`. It fails closed — a permanently broken export once a key is configured, not a hole.

---

## 11. Duplicated and divergent authorization logic

Role checks are duplicated — **four independent definitions of "privileged", two of which ignore permissions entirely**:

| # | Location | Rule |
|---|---|---|
| 1 | `authz.py:713` | `ADMIN_WRITE in granted` **or** role normalizes to `admin` → `ALL_PERMISSIONS` |
| 2 | `db.py:11043` `actor_is_admin` | role named `admin` **or** a `role_permissions` row for `perm-admin-write` |
| 3 | `db.py:11030` `_actor_can_view_raw_pii` | role name in `{admin, compliance_officer, dpo}` — **permissions ignored** |
| 4 | `visibility.py:67` `_UNSCOPED_ROLES` | role name in `{admin, qa_reviewer, compliance_officer, dpo}` — **permissions ignored** |

(1) and (2) agree in practice. (3) and (4) diverge from both, in both directions:

- **Permission revocation cannot remove raw-PII access or full-book visibility.** A role named `dpo` stripped of every grant still returns `True` from `_actor_can_view_raw_pii` and still resolves to scope `ALL`. Only renaming the role narrows it.
- **A real superuser is under-privileged for PII.** A role named `Platform Ops` holding `perm-admin-write` gets every route from `authz`, but `_actor_can_view_raw_pii` returns `False` and `visibility.resolve` returns `OWN`. Two subsystems disagree about whether the same actor is an administrator.

`_actor_can_view_raw_pii` admits its status in its own docstring (`db.py:11031-11035`): "Until Phase 5 auth carries a real role claim… There is no seeded 'Compliance Officer' role yet — Admin is the stand-in." It is still the live rule.

`require_admin` (`main.py:741`) survives on exactly one route (`main.py:2940`), which the registry also gates on `ADMIN_WRITE` (`authz.py:385`) — harmless redundancy, but it keeps definition (2) alive.

**H14 (P2) — dead policy.** `compliance_officer` and `dpo` are defined in `ROLE_DEFAULTS` (`authz.py:191`, `:200`) and `_UNSCOPED_ROLES` (`visibility.py:67`) but never seeded, so the entire compliance-officer grant set and its raw-PII allowance are unreachable; `COMPLIANCE_WRITE` in practice belongs only to `qa_reviewer` and admin. Two permissions gate no route: `perm-workqueue-write` (still granted by default to `supervisor` and `agent`, `authz.py:161`, `:174`) and `perm-redteam-run` (in no role at all). No route references a permission absent from the catalog.

---

## 12. What to do

Ordered by what changes the most for the least work.

1. **Fix the revocation fallback (P0-1).** Distinguish "no rows" from "revoked to empty", and make `GET /roles` report resolved grants rather than raw rows so the screen cannot contradict the enforcer. Add the test `test_explicit_grant_beats_default_so_revocation_works` should have been: revoke *all*, assert empty.

2. **Invert the `APP_ENV` default (P0-2).** `_IS_PROD = _APP_ENV not in {"dev", "test", "local"}`. One line flips the failure direction of eight controls at once and makes `APP_ENV=staging` safe instead of silently open. This also closes H16's open-by-default WebSocket upgrade.

3. **Settle `/a2a` (P0-3).** Either commit the ingress configuration that terminates mTLS and strips `X-SSL-Client-*` next to the code that depends on it, or stop trusting those headers. A security boundary that lives only in infrastructure nobody can see from the repo is not reviewable, and this one gates the single route that bypasses both auth layers.

4. **Give background work an identity of its own (H8).** Bind an explicit service principal in the worker, bot worker, voice bot and MCP paths, and add an `actor_kind='system'` path to `db._activity` so the honest value is representable. Today the audit trail cannot say "a machine did this", so it says a named person did. Same class of defect as `requestedVia` in report 11, and the same fix shape.

5. **Collapse the four definitions of "admin" (§11) onto `authz`.** `_actor_can_view_raw_pii` and `_UNSCOPED_ROLES` should consult permissions, not role names, so revoking a grant actually revokes it. This is the one place the otherwise-excellent central registry has been quietly forked.

6. **Extend the totality proof to `app.routes` (H15).** `_app_routes()` filters to `APIRoute`/`APIWebSocketRoute`; widening it to every route object and classifying the four documentation routes closes the only hole in an otherwise airtight mechanism — and it is a change to one test helper.

7. **Give the two exempt lists one source (H5).** `_AUTH_EXEMPT_PREFIXES` and `PUBLIC_ROUTES` express the same policy twice and already disagree on two routes. Derive one from the other, or add the test asserting they agree — the same shape of test that already keeps the route registry honest.

Items 1–3 are correctness. Items 4–7 are structural: they are what stops the *next* defect, and each has a working model already in this repository to copy.

---

## Findings index

**P0**
- **P0-1** — Total revocation restores a role's full defaults; the Roles screen then displays the opposite of what is enforced. `authz.py:702-709`, `db.py:496`, `main.py:2851`, `roles.tsx:26-34`
- **P0-2** — Eight fail-closed controls all key off `APP_ENV ∈ {prod, production}`, default `dev`, no allowlist. `main.py:204-205`, `actor_context.py:54-55`
- **P0-3** — `POST /a2a` bypasses both auth layers and authenticates on spoofable headers. `main.py:278-279`, `a2a.py:23-32`

**P1**
- **H1** — Shared key + `X-Actor-User-Id` is full identity assumption; `API_KEY_MAP` bypassable by a stale `API_KEY`. `actor_context.py:189-199`, `:221-226`
- **H2** — Twilio webhooks auth-exempt *and* signature-optional outside prod. `main.py:3392`, `:3396`
- **H3** — No key rotation, expiry, revocation, per-key audit, or user-deactivation concept. `db.py:439`, `actor_context.py:68-73`
- **H6** — Read scoping is fail-open by construction and reaches 14 of ~491 query sites. `db.py:241-255`, `db.py:21`
- **H7** — Writes stop at tenant granularity; four PATCH paths are write-IDOR within the tenant. `db.py:263-290`, `visibility.py:42-49`
- **H8** — Process-default actor is an admin, and `db._activity` hardcodes `actor_kind='human'`, so machine writes are filed as a named person's manual actions. `db.py:649`, `:658`, `seed_postgres.py:690-691`
- **H11** — Eleven invisible gates; `/roles` exposes the full RBAC matrix at `BOT_READ`. `Sidebar.tsx:57-104`, `authz.py:360`
- **H15** — `/docs`, `/redoc`, `/openapi.json` sit outside both the guard and the coverage proof. `tests/test_authz.py:29-35`, `main.py:585`
- **H16** — WebSocket routes get no registry authorization; the fallback fails open outside prod. `main.py:533-534`, `:3479`
- **H17** — `POST /interactions` accepts `handlerUserId` from the body unvalidated. `db.py:8339`, `:5320`

**P2**
- **H4** — Both invalidation functions are never called; revocation lags 30s per process. `authz.py:652-666`
- **H5** — The two exempt lists disagree on two signature-authenticated webhooks. `authz.py:229`, `:233`
- **H9** — A second, better credential system (MCP) is mintable from the weaker one, and its keys bind no user. `main.py:2483-2512`
- **H10** — Two non-constant-time secret comparisons. `main.py:4595`, `:3414-3417`
- **H12** — 403 is indistinguishable from a network failure in the UI. `config.ts:130-142`
- **H13** — One raw `fetch` bypasses auth headers; fails closed. `sandbox.lazy.tsx:432`
- **H14** — Dead policy: two unseeded roles, two permissions gating no route. `authz.py:191`, `:200`
- **H18** — Webhook signing keyed with the stored digest: a documented tradeoff whose limit is worth stating. `webhooks_dispatch.py:105-111`, `:26-31`
- **H19** — `GET /pay/{token}` renders expired intents indefinitely. `main.py:786-792`

---

## Checked and cleared

Recorded so the next audit does not re-spend the effort.

- **Route coverage.** Zero unregistered routes, zero stale policy rows, across 318 routes. `26 + 292 = 318 = 314 + 4` closes exactly. `authz.py:879-895`, `tests/test_authz.py:38-40`
- **The coverage proof runs in CI** and is not defeated by path filtering — `backend/**` contains `authz.py`, `main.py` and the test. Unverifiable from the repo: whether the workflow is a required status check.
- **No duplicate routes, no mounts, no `StaticFiles`, no `include_router`, no `add_api_route`.** Nothing bypasses the parent app's global dependency by mounting.
- **No method-mismatch gap.** FastAPI sets `route.methods` directly and never adds an implicit `HEAD`, so a `HEAD` request 405s at routing rather than reaching the guard unclassified.
- **Prefix over-matching.** `main.py:280` is segment-bounded; `/ws` does not exempt `/ws-admin`, `/me` does not exempt `/metrics`. Regression-pinned.
- **The guard reads the path template, not the raw path** — parameterised routes match the registry. `main.py:536-537`
- **The guard uses the middleware-authenticated actor**, explicitly not the ContextVar fallback. `main.py:539-542`
- **Grant and role resolution fail closed** on database error. `authz.py:730-735`, `:792-794`
- **Unknown roles get the tightest visibility scope.** `visibility.py:127-129`
- **The visibility predicate is constant**, scope in bind parameters, alias validated with `isidentifier()`. `visibility.py:139-163`
- **Seeded role names map correctly** onto `_UNSCOPED_ROLES`/`_TEAM_ROLES`. No silent mismatch.
- **`POST /handoff/{id}/claim` is correctly ownership-guarded.** An agent cannot claim another agent's handoff. `db.py:4576,4598,4603`
- **`asyncio.to_thread` propagates ContextVars** — the ~25 in-request sites are fine. Only process boundaries lose the actor.
- **Production boot refuses missing credentials**, backed by a second per-request refusal. `main.py:431-433`, `actor_context.py:203-205`
- **`_assert_hardening_gate` refuses production boot** while RLS and PII encryption are inactive. `main.py:400-418`
- **API-key comparison is constant-time** on every path. `actor_context.py:172-175`
- **Payment and WhatsApp webhook HMACs fail closed** on an unset secret and use `compare_digest`.
- **Pay-link tokens are 192 bits** of `secrets.token_urlsafe`, single-use, expiry-checked on completion.
- **`/metrics` is not exempt** and is permission-gated. `authz.py:581`
- **No API route creates, renames, or assigns roles.** The only writes to `roles`/`user_roles`/`role_permissions` outside seeds and migrations are inside `replace_role_permissions`, reachable only at `ADMIN_WRITE`. The "role named admin" escalation at `authz.py:713` therefore needs database access, not an API call — a latent hazard if role CRUD is ever added, since role name is free text with no reserved-name check.
- **`POST /agent-studio/skills/run-script` does not execute arbitrary code** — a two-entry allowlist of pure arithmetic functions.
- **MCP HTTP is a genuinely separate process** with its own complete auth, correctly outside `assert_registry_covers`.
- **No frontend-only authorization exists.** Every gate is server-side.
- **No identity in browser storage.** The single `localStorage` use is the theme toggle.
- **Auth headers are attached uniformly**, including on the SSE stream — which is why it uses `fetch` rather than `EventSource`.
- **`backend/.env` is gitignored and untracked.** On-disk plaintext secrets only, already ticketed in `docs/ops/vault-inventory.md`.

---

## 13. Two corrections to my own framing

Recorded because a reader deserves to know where this report changed its mind.

**RLS is deferred, not overlooked.** My first reading was "a 633-line safety net that nothing attaches." That was wrong. `main.py:388-397` names RLS tenant isolation as a known deferred control and `_assert_hardening_gate` refuses production boot because of it. The accurate finding is narrower and appears in §8: the escape hatch downgrades that refusal to a log line, and activation is an unautomated manual sequence.

**The route registry is total over the API route table, not over `app.routes`.** I first wrote that the registry is provably total with no qualification. The route analyst was right to narrow it: FastAPI's four generated documentation routes are plain Starlette `Route` objects, invisible to both the guard and the proof. The claim is now stated with that boundary (H15).

**A third, smaller correction:** the permission catalog holds **35** entries (`authz.py:106-140`), not 36 as I first counted.
