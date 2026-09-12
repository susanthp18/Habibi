# Microsoft Entra ID SSO for a FastAPI + React operator console (2026)

Research brief for Habibi: internal operator console, FastAPI backend + TanStack Start / React frontend, `bigtapp.ai` domain only, existing local RBAC (`users`, `roles`, `permissions`, `user_roles`, route registry keyed by `user_id`). Current auth is static `X-API-Key` / Bearer. Local user IDs look like `priya-nair`, not Entra object IDs.

**Method.** Primary sources only: Microsoft Learn (Entra ID / Microsoft identity platform), MSAL.js / MSAL Python, FastAPI security docs. Retrieved **2026-09-08**. Microsoft Learn pages do not always expose a last-updated date in the fetched HTML; dates below are retrieval dates unless the page itself states a date.

**Not invented.** Where Microsoft does not document a control (for example there is no Entra `hd` claim), that absence is stated.

---

## Recommended architecture for this app

This is a **workforce, single-tenant, line-of-business SPA + API**. It is not a customer-facing CIAM app and should not use Microsoft Entra External ID (external tenant) or Azure AD B2C.

```
Operator browser
  └─ React / TanStack Start (public client)
        MSAL.js v5  →  OIDC + OAuth 2.0 auth code + PKCE
        authority: https://login.microsoftonline.com/{bigtapp-tenant-id}/v2.0
        acquires access token for API scope api://{api-app-id}/access_as_user
        Authorization: Bearer <access_token>
              │
              ▼
        FastAPI (resource / web API)
          1. Validate JWT (signature via JWKS, iss, aud, tid, exp/nbf, scp)
          2. Map oid (+ tid) → local users.user_id  (or refuse if unmapped)
          3. Authorize with existing local RBAC (roles / permissions / route registry)
```

**Two app registrations in the BigTapp workforce tenant**

| Registration | Account type | Platform | Role |
|---|---|---|---|
| SPA (operator console) | Accounts in this organizational directory only | Single-page application redirect URI | Public client. `client_id` used by MSAL. Requests delegated scope on the API. |
| API (FastAPI) | Same, single-tenant | Expose an API (`api://{api-client-id}/access_as_user` or similar) | Resource. Access token `aud` is this app. `requestedAccessTokenVersion` / `accessTokenAcceptedVersion` = `2`. |

Microsoft’s SPA + API pattern: the SPA is a public client; the API is a protected resource that validates **access tokens** issued **for that API**. The SPA must not treat the ID token as an API credential, and must not inspect access tokens. ([Access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens), [Protected web API](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-overview), retrieved 2026-09-08.)

**Identity mapping (do not replace local RBAC)**

- Entra authenticates. The app authorizes. ([Authentication vs authorization](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-vs-authorization), retrieved 2026-09-08.)
- Stable key: `oid` + `tid`. Not `preferred_username`, `email`, `upn`, or `unique_name`. ([ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference), [Claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation), retrieved 2026-09-08.)
- Add columns on `users`: `entra_oid` (GUID, unique), optionally `entra_tid`, `upn`/`email` as **display/hint only**. Keep existing `user_id` (`priya-nair`) as the RBAC key.
- **Pre-provision** operator rows. First login that cannot map `oid` → existing user is **403**, not JIT-create with permissions. This matches assignment-required + a regulated console.

---

## 1. Recommended protocol (2025–2026): OIDC vs SAML vs WS-Fed

**For SPA + API: OpenID Connect (authentication) + OAuth 2.0 (authorization).** Implicit grant is not recommended. SAML is not the SPA path. WS-Federation is not recommended for new apps.

| Protocol | Microsoft’s current position | Fit for this app |
|---|---|---|
| **OIDC + OAuth 2.0 authorization code + PKCE** | Default for new SaaS; **required for SPAs and mobile**. | **Use this.** |
| **SAML 2.0** | Fully supported; choose only for legacy / procurement mandates. Challenging for SPA. Microsoft does not ship SAML SDKs. | Do not use for this console. |
| **WS-Federation** | Federation metadata still covers SAML and “the older WS-Federation standards. While fully supported, we don't recommend WS-Federation for new applications.” | Do not use. |

Sources (retrieved 2026-09-08):

- [SAML versus OpenID Connect decision guide](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/saml-vs-oidc-decision-guide): “If unsure, default to OIDC for new SaaS development.” SPAs: choose OIDC.
- [Plan your SSO integration (ISVs)](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/plan-sso-integration-isv): “Single-page applications (SPAs) and mobile apps: must use OIDC.” “SPAs → OIDC required (client-side token management).”
- [Application types](https://learn.microsoft.com/en-us/entra/identity-platform/v2-app-types): SPAs use OIDC; “Use the authorization code flow with Proof Key for Code Exchange (PKCE) when developing SPAs. This flow is more secure than the implicit flow, which is no longer recommended.”
- [Authentication vs authorization](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-vs-authorization): OIDC for authentication, OAuth 2.0 for authorization. “OpenID Connect is commonly used for apps that are purely in the cloud, such as mobile apps, websites, and web APIs.” SAML is the enterprise / AD FS pattern.
- [Authenticate applications and users](https://learn.microsoft.com/en-us/entra/architecture/authenticate-applications-and-users): WS-Federation not recommended for new applications; for new development use OIDC; MSAL always requests an OIDC ID token.

**Multitenant vs single-tenant.** ISV gallery guidance prefers multitenant. This operator console is **internal to one organization**. Microsoft’s single-tenant audience is: “Accounts in this directory only” — “Use this option if your target audience is internal to your organization.” ([Single and multitenant apps](https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps), retrieved 2026-09-08.) Register **single-tenant**. Use tenant-specific authority, not `/common` or `/organizations`.

---

## 2. Restricting sign-in to `bigtapp.ai` — authoritative vs cosmetic

There is **no Entra equivalent of Google’s `hd` claim**. Domain restriction is a **stack of controls**. Checking `email` / `preferred_username` / `upn` in the app is **not** a security boundary.

### Authoritative (actually stops tokens / sign-in)

| Control | What it does | Limits |
|---|---|---|
| **Single-tenant app registration** + **tenant-specific authority** `https://login.microsoftonline.com/{tenant-id}/v2.0` | Tokens are issued in this tenant. `iss` is this tenant’s STS. Personal Microsoft accounts and other tenants are not the sign-in audience. | **Guests already in this tenant still authenticate** unless you also assign users / Conditional Access / app-side mapping. OIDC `{tenant}` = Directory ID “Only users from a specific Microsoft Entra tenant (**directory members** with a work or school account **or directory guests** with a personal Microsoft account).” ([OIDC](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)) |
| **Validate `iss` and `tid` on the API** | Reject any token whose tenant is not BigTapp’s GUID. Required even for “single-tenant” apps. For tenant-specific metadata, `iss` must **exactly** match. Also check `tid` is a GUID and matches `iss`. ([Access tokens — validate issuer](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens), [Claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation)) | Does not by itself exclude guests **inside** that tenant. |
| **Enterprise app: Assignment required = Yes** | Users/services not assigned cannot sign in or obtain an access token for the app. ([Restrict an app to a set of users](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users)) | **Global Administrator is exempt.** User consent is disabled when assignment is required; grant admin consent. Assign only `bigtapp.ai` members (or a security group of them). |
| **Conditional Access** targeting this cloud app | Can require MFA, compliant device, and **include/exclude guest or external user types** (B2B collaboration guests, members, local guests, etc.). ([CA users, groups](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-conditional-access-users-groups)) | Policy design is tenant-admin owned. CA is an IdP gate, not an app claim. |
| **API refuses unmapped `oid`** | Even a valid token cannot use the console unless a local `users` row exists. | This is the last line of defense and belongs in FastAPI. |

### Cosmetic or wrong tool for this app

| Control | What it actually is |
|---|---|
| **`domain_hint`** | Optional authorize parameter. Skips email-based home-realm discovery; can auto-accelerate federation. OIDC: “slightly more streamlined user experience.” Auth code flow: apps can pass it on reauth. Implicit-flow docs add that it “prevents guests from signing into this application, and limits the use of cloud credentials such as FIDO” — still a **client-supplied hint**. An attacker omits it. **Not a token-validation rule.** ([OIDC](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc), [Auth code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [Implicit flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-implicit-grant-flow)) |
| **`login_hint`** | Prefills username. UX only. |
| **Home Realm Discovery policy** | Tenant/app policy about whether domain hints auto-accelerate federated IdPs. Not “only `@bigtapp.ai` may use this SaaS app.” ([HRD policy](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/home-realm-discovery-policy)) |
| **Tenant restrictions v1/v2** | **Corporate proxy / network** headers (`Restrict-Access-To-Tenants`) so **employees on the company network** cannot sign in to **other** tenants’ SaaS. Wrong layer for locking **this** app to one verified domain. ([Tenant restrictions](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/tenant-restrictions), [TR v2](https://learn.microsoft.com/en-us/entra/external-id/tenant-restrictions-v2)) |
| **Optional claims (`email`, `upn`)** | Can be added to ID/access tokens. Still **mutable**. Microsoft: never use for authorization. ([Optional claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims), [Claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation)) |
| **Issuer “domain” string** | `iss` is `https://login.microsoftonline.com/{tid}/v2.0` (or v1 `https://sts.windows.net/{tid}/`), not `bigtapp.ai`. |
| **`hd` / ID-token “domain restriction” claim** | **Not an Entra claim.** Google OpenID Connect uses `hd`. Do not look for `hd` in Entra JWTs. |

### Validating `preferred_username` / `upn` / `email`

Microsoft’s rule is explicit:

> Never use claims like `email`, `preferred_username` or `unique_name` to store or determine whether the user in an access token should have access to data. These claims aren't unique and can be controllable by tenant administrators or sometimes users… Also don't use the `upn` claim for authorization. While the UPN is unique, it often changes over the lifetime of a user principal. ([Claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation), retrieved 2026-09-08.)

> Don't use human-readable data to identify a user. Use `sub` or `oid`… To correctly store information per-user, use `sub` or `oid`… with `tid` used for routing or sharding. If you need to share data across services, `oid` and `tid` is best. ([ID token claims — reliably identify a user](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference), retrieved 2026-09-08.)

A **defense-in-depth** check that `preferred_username` or `upn` ends with `@bigtapp.ai` is acceptable **after** signature/`tid`/`oid` validation, as a tripwire — not as the allow decision. Guest UPNs look like `alice_contoso.com#EXT#@bigtapp.onmicrosoft.com` and would fail a naive `@bigtapp.ai` suffix check (good), but a **member** who later changes UPN would also fail (bad if you keyed RBAC on UPN).

**Practical Entra + app combo for `bigtapp.ai` only**

1. Single-tenant registrations; authority = tenant GUID.
2. Assignment required; assign a security group of internal members (dynamic group `user.userPrincipalName -endsWith "@bigtapp.ai"` is an Entra **directory** filter, not a token claim — still pair with assignment).
3. Conditional Access on this app: block guest/external user types if the tenant uses B2B.
4. API: `tid` allowlist + `oid` must exist in `users` + local RBAC.

---

## 3. Mapping Entra identity onto existing local RBAC

Microsoft’s split: **Entra authenticates; the resource authorizes**. OAuth scopes/`roles` in the token are **one** authorization input, not the only one:

> The `roles`, `groups`, `scp`, and `wids` claims are not an exhaustive list of how a resource might authorize a user… The target resource may use another method to authorize access to its protected resources. ([Access token claims](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference), retrieved 2026-09-08.)

Delegated access: the **client** needs scopes; the **user** is still authorized by whatever RBAC the resource uses (Entra directory roles, Exchange RBAC, **or the application’s own RBAC**). ([Permissions and consent](https://learn.microsoft.com/en-us/entra/identity-platform/permissions-consent-overview), retrieved 2026-09-08.)

That is the documented basis for **“IdP authenticates, app authorizes.”** Keep the existing permission registry keyed by `user_id`.

### JIT vs pre-provisioned users

| Pattern | Microsoft documentation | For this console |
|---|---|---|
| **Assignment required + admin assigns users/groups** | Tokens are not issued unless assigned. ([Restrict app](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users)) | **Required.** |
| **SCIM automatic provisioning** | Entra creates/updates/deletes app identities via SCIM 2.0; SSO (OIDC/SAML) is separate. “When used with federation standards… end-to-end standards-based solution.” ([App provisioning](https://learn.microsoft.com/en-us/entra/identity/app-provisioning/user-provisioning)) | Optional later if you want joiner/leaver automation. You would implement a SCIM endpoint and map to `users` / `user_roles`. Not required to ship SSO. |
| **SAML JIT provisioning** | Documented as a SAML automation option. ([App provisioning](https://learn.microsoft.com/en-us/entra/identity/app-provisioning/user-provisioning)) | Irrelevant if you use OIDC. |
| **App-side JIT (create user on first OIDC login)** | Not a Microsoft-recommended substitute for assignment. Guest docs: a user object is created **in Entra** when invited, not in your app. | **Do not JIT-grant operator permissions.** First-seen `oid` with no row → deny. Optionally create a **disabled** stub for an admin to link. |

### App Roles vs groups vs SCIM

| Mechanism | Token claim | Microsoft guidance | Use here |
|---|---|---|---|
| **App roles** | `roles` | Defined on the **API** app registration; assigned on the enterprise app. Travel with the app (unlike group GUIDs). SaaS apps often map tenant groups → app roles. ([Add app roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps)) | Optional **coarse** sync (e.g. `Operator`, `Auditor`) → local `roles`. Not the permission catalog. |
| **Groups** | `groups` (GUIDs) | Tenant-specific; overage at **200 groups in JWT** (150 SAML) — then Graph query required. “Groups assigned to the application” recommended for large orgs. ([Optional claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims), [Access token claims](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference)) | Fragile as sole authz. Do not put 50 route permissions in group claims. |
| **OAuth scopes (`scp`)** | `scp` | What the **client app** may do on behalf of the user (e.g. `access_as_user`). Verify on every API call. ([Protected API — verify scopes](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-verification-scope-app-roles)) | One delegated scope is enough. Fine-grained routes stay in local RBAC. |
| **SCIM** | N/A (provisioning API) | Lifecycle of users/roles **in the app**. | Optional; complements SSO, does not replace token validation. |

App roles vs groups (Microsoft table): app roles are app-specific and appear in `roles`; groups are tenant-wide and appear in `groups`. Developers prefer app roles when they “describe and control the parameters of authorization in their app themselves,” because group IDs break across tenants. ([Add app roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps), retrieved 2026-09-08.)

You are **not** a multi-tenant SaaS. Local RBAC already exists. Treat Entra groups/app roles as **optional identity-source hints**, not the permission database.

### Why not put fine-grained permissions in Entra

1. **Token size / overage.** JWT group limit 200; overage forces Graph calls with extra permissions and failure modes. ([Access token claims](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference))
2. **App role cardinality.** Roles count toward **application manifest limits**. They are designed as coarse roles (`Survey.Create`), not per-route flags. ([Add app roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps))
3. **Wrong layer.** Entra roles/groups are directory objects administered in the Entra admin center. Habibi’s registry is route-level and already keyed by `user_id`.
4. **Microsoft already separates client scopes from user authorization.** Scopes say the SPA may call the API; they do not replace the user’s privileges on the resource. ([Permissions and consent](https://learn.microsoft.com/en-us/entra/identity-platform/permissions-consent-overview))
5. **ACL-without-roles is an allowed pattern** (`AllowWebApiToBeAuthorizedByACL` in Microsoft.Identity.Web) — the API may authorize by its own list rather than `roles`/`scp` alone. ([Verify scopes and app roles](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-verification-scope-app-roles))

### Mapping strategy onto existing tables

1. Validate token (section 4).
2. `SELECT * FROM users WHERE entra_oid = :oid` (and `entra_tid` matches).
3. If missing: 403. Admin links Entra user to `priya-nair` (or creates the local user first, then links).
4. Load `user_roles` → `permissions` as today.
5. Optional: if `roles` claim present, **sync** to local roles on login (never the only check).
6. Do not change the public permission API from `user_id` to `oid` unless you migrate every caller.

`sub` is pairwise per application ID. SPA and API have **different client IDs**, so **`sub` differs**. Use **`oid`** (same across apps in the tenant) as the correlation key. ([ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference))

---

## 4. Token validation for FastAPI

### What validates what

- **Web API must validate access tokens.** Check `aud` is **this API**.
- **SPA / public client must not validate access tokens** (opaque to the client; may be encrypted later). SPA does not need to validate ID tokens for security of the API call; TLS to Entra protects the code flow. ([Access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens), retrieved 2026-09-08.)

MSAL.js acquires the token; FastAPI is the resource server.

### FastAPI / MSAL Python reality

- FastAPI ships `HTTPBearer` and `OpenIdConnect` as **OpenAPI stubs**. Built-in JWT tutorial uses **your own HS256 secret**, not Entra JWKS. ([FastAPI HTTPBearer](https://fastapi.tiangolo.com/reference/security), [OAuth2 scopes](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes), retrieved 2026-09-08.)
- **There is no official FastAPI + Entra tutorial** on Microsoft Learn as of this retrieval. Python samples: Flask/Django **web apps** (MSAL Python confidential client, auth code) and **Python Azure Functions as a web API**. ([Code samples](https://learn.microsoft.com/en-us/entra/identity-platform/sample-v2-code), GitHub [ms-identity-python-webapi-azurefunctions](https://github.com/Azure-Samples/ms-identity-python-webapi-azurefunctions).)
- **MSAL Python acquires tokens** (public or confidential client). It is not the API’s JWT validator. ([MSAL Python](https://learn.microsoft.com/en-us/entra/msal/python/), retrieved 2026-09-08.)
- Implement validation with a JWT library (PyJWT / Authlib) against Entra’s OIDC metadata + JWKS, following [Access tokens — Validate tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens).

### Validation checklist (v2 access token)

OIDC discovery (tenant-specific, recommended for this LOB app):

`https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration`

JWKS: `jwks_uri` from that document (typically `https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys`).

Match token `ver` to the metadata version (v2 token → v2 discovery). Refresh signing keys (Microsoft: about every 24 hours; handle rollover via `kid`). ([Access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens))

| Check | Claim / source | Rule |
|---|---|---|
| Signature | header `kid` + JWKS, `alg` RS256 | Reject unknown `kid`, `alg=none`, or key not in JWKS. |
| Issuer | `iss` | Exact match `https://login.microsoftonline.com/{tenant-id}/v2.0` (v2). Do not use `/common` metadata for this app. |
| Tenant | `tid` | Must equal BigTapp tenant GUID; must match the GUID in `iss`. |
| Audience | `aud` | v2: **API application (client) ID**. v1: App ID URI (e.g. `api://{id}`). Reject tokens for Graph or the SPA client ID. |
| Lifetime | `nbf`, `exp`, `iat` | Reject expired / not-yet-valid. Clock skew small (minutes). |
| Scope | `scp` | Must contain the API’s delegated scope (e.g. `access_as_user`). |
| Subject present | `oid` (and typically `sub`) | Need `oid` to map the user. Warning: validating only `tid` + presence of `oid` can authorize **service principals** in the tenant; require a **user** token (delegated `scp` present; optionally `idtyp` ≠ `app`). ([Claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation)) |
| Client | `azp` (v2) | Optionally allowlist the SPA’s client ID so only that public client can call the API. |
| Token version | `ver` | Expect `2.0` if API manifest requests v2. |

Do **not** authorize on `email`, `preferred_username`, `unique_name`, `upn`.

### Rejecting other tenants (including “single-tenant” misconfig)

1. Register **Accounts in this organizational directory only**.
2. MSAL `authority`: tenant GUID, never `common` / `organizations` / `consumers`.
3. API `TenantId` / `iss` allowlist: that GUID only. Microsoft: for LOB, specify TenantId; `common` / `organizations` accept any org. ([Protected web API](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-overview))
4. If someone points MSAL at `/common`, Entra may still issue a token for **this** tenant for a guest or a user who picks an account — **API `tid` check** is what fails closed.
5. Personal MSA tenant GUID is `9188040d-6c67-4c5b-b112-36a304b66dad`. Reject it. ([ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference))

Multitenant apps that use `/common` metadata **must** substitute `{tenantid}` in `iss` and bind `tid` ↔ `iss` ↔ signing key issuer. You should **not** use that path. ([Access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens))

### SPA acquiring tokens for the API (client ID vs API registration)

```
SPA client_id  ≠  API client_id
loginRequest / acquireTokenSilent scopes: [ "api://{API-CLIENT-ID}/access_as_user" ]
  (or the App ID URI + scope name you exposed)
```

- User signs in to the **SPA** (OIDC: `openid`, `profile`, `offline_access` as needed).
- MSAL then requests an **access token whose audience is the API**.
- API validates `aud` = API id, `azp` = SPA id (optional), `scp` = exposed scope.
- Preauthorize the SPA on the API so users are not prompted for consent on every scope; with assignment required, grant **admin consent**. ([Restrict app](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users), [Permissions](https://learn.microsoft.com/en-us/entra/identity-platform/permissions-consent-overview))

Microsoft sample scope form: `api://.../access_as_user`. ([Protected web API](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-overview))

SPA: `acquireTokenSilent` → on `InteractionRequiredAuthError` → `acquireTokenPopup` or `acquireTokenRedirect`. ([Acquire a token — SPA](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-spa-acquire-token))

**PKCE** is **required** for SPAs on the Microsoft identity platform. No client secret in the browser. Redirect URI type **`spa`** (CORS on `/token`). ([Auth code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [Third-party cookies](https://learn.microsoft.com/en-us/entra/identity-platform/reference-third-party-cookies-spas))

---

## 5. Domain restriction pitfalls

### Guests / B2B / `#EXT#` UPNs

- Single-tenant apps still allow **guest accounts in that directory**. ([Single and multitenant apps](https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps), [OIDC tenant values](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc))
- Guest UPN: `john_contoso.com#EXT#@fabrikam.onmicrosoft.com`. ([B2B user properties](https://learn.microsoft.com/en-us/entra/external-id/user-properties), retrieved 2026-09-08.)
- `idp` differs from `iss` for guests (home STS or `live.com`). Do not use `idp` to correlate users across tenants. Treat a guest in tenant A as a **different user** from the same person in tenant B. ([ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference))
- `UserType` Guest vs Member is independent of how they sign in. External **members** exist (multi-tenant orgs). ([B2B user properties](https://learn.microsoft.com/en-us/entra/external-id/user-properties))
- **Assignment required** + assign only members, and/or CA exclude “B2B collaboration guest users,” plus app mapping to local users.

### Personal Microsoft accounts

- Do not select “any org + personal Microsoft accounts.”
- Do not use authority `consumers` or `common`.
- Reject `tid == 9188040d-6c67-4c5b-b112-36a304b66dad`.
- Invited MSA guests can still appear **inside** the workforce tenant (`Identities` = Microsoft account). Assignment required blocks them unless someone assigned them.

### Accidental multi-tenant

- App registration “Accounts in any Microsoft Entra directory.”
- MSAL `authority` `/common` or `/organizations`.
- API validation using `common` metadata **without** `tid` allowlist.

Microsoft’s own ISV note: if you use tenant-independent endpoints, **you** must filter `iss` / `tid` to an allowlist. ([Authenticate applications and users](https://learn.microsoft.com/en-us/entra/architecture/authenticate-applications-and-users), retrieved 2026-09-08.)

### Global Administrator bypass

Assignment required “will not be applicable” for Global Administrator. ([Restrict app](https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users)) App-side `oid` mapping still applies — keep GA out of `users` unless intended.

---

## 6. SPA auth: what Microsoft recommends now

| Topic | Current recommendation |
|---|---|
| Flow | Authorization code + **PKCE**. Implicit **not recommended**; RFC 9700 cited. Silent iframe implicit SSO is broken by third-party cookie blocking. ([Implicit grant](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-implicit-grant-flow), [MSAL flows](https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows), [Third-party cookies](https://learn.microsoft.com/en-us/entra/identity-platform/reference-third-party-cookies-spas)) |
| Library | MSAL (`PublicClientApplication`). Do not use ADAL. ([MSAL overview](https://learn.microsoft.com/en-us/entra/identity-platform/msal-overview)) |
| Redirect URI | Platform **Single-page application** (`spa`), not Web. |
| Refresh | SPA refresh tokens issued to `spa` URIs: **24-hour** lifetime (not 90-day). After 24h, interactive visit to login (redirect or popup). Access tokens ~60–90 minutes. ([Third-party cookies](https://learn.microsoft.com/en-us/entra/identity-platform/reference-third-party-cookies-spas), [Access tokens — lifetime](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens), [Acquire token SPA](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-spa-acquire-token)) |
| Token storage | Default examples use `sessionStorage` (“more secure”) vs `localStorage` (“SSO” across tabs). XSS can steal refresh tokens from either; 24h RT is the documented mitigation. ([SPA quickstart](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-single-page-app-sign-in), [Third-party cookies — security of RTs](https://learn.microsoft.com/en-us/entra/identity-platform/reference-third-party-cookies-spas), [MSAL init](https://learn.microsoft.com/en-us/entra/identity-platform/msal-js-initializing-client-applications)) |
| Redirect vs popup | Popup if you must not leave the page; **redirect** if popups are blocked. IE: redirect. Redirect is the more reliable default for an operator console. ([Acquire token SPA](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-spa-acquire-token)) |
| Pattern | `acquireTokenSilent` first; interactive fallback. One `PublicClientApplication` instance. |

### MSAL.js 3 vs 4 vs 5 (as of 2026-09-08)

The question “3 vs 4” is stale. Microsoft’s JS overview (retrieved 2026-09-08):

| Library | Active | LTS | Out of active support |
|---|---|---|---|
| `@azure/msal-browser` | **v5.x** (e.g. v5.21.0 released 2026-09-02) | v2.x | **v3.x and v4.x** on `msal-lts` |
| `@azure/msal-react` | v5.x | v1.x | — |

Sources: [MSAL JavaScript overview](https://learn.microsoft.com/en-us/entra/msal/javascript/), [v4 → v5 migration](https://learn.microsoft.com/en-us/entra/msal/javascript/browser/v4-migration), [GitHub msal-browser v5.21.0](https://github.com/AzureAD/microsoft-authentication-library-for-js/releases/tag/msal-browser-v5.21.0).

v5 notes that matter for a new app: `initialize()` (or `createStandardPublicClientApplication`); optional AES-GCM encryption of localStorage cache; COOP popup support; do not start on v3/v4.

React: `@azure/msal-react` + `MsalProvider`. TanStack Start is not a Microsoft-documented host; treat the client like any SPA (PKCE, `spa` redirect, no secrets on the server unless you add a confidential BFF — Microsoft’s documented SPA path is browser MSAL, not a BFF).

---

## 7. 2025–2026 platform changes

### Azure AD rename

Renamed to **Microsoft Entra ID** (announced / rolled through 2023; SKU names 2023-10-01). Login URLs, APIs, and MSAL **unchanged**. ADAL deprecated. Azure AD B2C **name unchanged**. ([New name for Azure AD](https://learn.microsoft.com/en-us/entra/fundamentals/new-name), retrieved 2026-09-08.)

### Workforce vs External ID (CIAM)

| | **Workforce tenant** (use this) | **External tenant / External ID** |
|---|---|---|
| Purpose | Employees, LOB, Microsoft 365, B2B guests | Consumer / customer CIAM apps |
| This console | **Yes** | No — not a customer app |
| B2B | Guests in the **same** workforce directory | Separate customer directory |

Azure AD B2C: **not available to new customers effective 2025-05-01**. Next-gen CIAM is External ID. Irrelevant if you stay on workforce SSO. ([External ID overview](https://learn.microsoft.com/en-us/entra/external-id/external-identities-overview), [New name — B2C exception](https://learn.microsoft.com/en-us/entra/fundamentals/new-name))

MSAL Python documents CIAM authority as `https://{subdomain}.ciamlogin.com` for **customer** tenants — do not use that for BigTapp employees. ([MSAL Python](https://learn.microsoft.com/en-us/entra/msal/python/))

### Token versions (v1 vs v2)

- **OIDC/OAuth endpoint:** new apps should use **v2.0** (`.../oauth2/v2.0/authorize|token`). ([ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference))
- **Access token shape** is owned by the **resource** (API), via app manifest:
  - Learn **Access tokens** page: `requestedAccessTokenVersion` — `null`/`1` → v1.0 tokens; `2` → v2.0.
  - Learn **Protected web API** page: property name `accessTokenAcceptedVersion` — `2` → v2.0; `null` → v1.0.
  - Set **2** for a new API so `aud` is the API **client ID**, `preferred_username` is available, `azp` instead of `appid`. Apps that support personal accounts **must** accept v2.0. ([Access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens), [Protected web API](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-overview))

v1 `iss`: `https://sts.windows.net/{tid}/`. v2 `iss`: `https://login.microsoftonline.com/{tid}/v2.0`. Validate against the matching discovery document.

---

## What MUST be done in Entra vs in the app

### Entra (admin / app registration)

- Workforce tenant; two app registrations (SPA + API), **single-tenant**.
- SPA: `spa` redirect URIs; no implicit grant; no secret.
- API: Application ID URI; delegated scope; `requestedAccessTokenVersion` / `accessTokenAcceptedVersion` = 2; preauthorize SPA; admin consent.
- Enterprise apps: **Assignment required**; assign member group only.
- Conditional Access: MFA (and guest block if B2B is used).
- Optional: app roles as coarse labels; SCIM later.
- Do not register as External ID / multi-tenant / MSA.

### App (FastAPI + React)

- MSAL.js v5 in the SPA; tenant authority; acquire API access token; `Authorization: Bearer`.
- FastAPI: JWKS validate every request; `iss`/`tid`/`aud`/`scp`/`exp`; map `oid` → `users`; existing RBAC.
- Stop accepting static API keys for **browser operator** sessions (or lock keys to service accounts only).
- Store `entra_oid` on `users`; never key permissions on UPN/email.

---

## Risks if they only add MSAL on the frontend and keep API keys

Microsoft: the **API** must validate access tokens meant for it. A SPA that “signs in with Entra” but still calls FastAPI with `X-API-Key` means:

1. **Entra is UX-only.** Anyone with the static key bypasses SSO, MFA, CA, assignment required, and offboarding.
2. **Confused deputy / stolen key.** Keys in SPA bundles, env, or shared operator docs are bearer credentials with no user identity.
3. **No `oid` on the request.** Local RBAC cannot bind an Entra user to `priya-nair`; audit still shows a shared key.
4. **False compliance story.** RBI/DPDP-style access control needs the authenticated **person**, not a shared secret.
5. **ID token sent as API Bearer.** ID token `aud` is the **SPA**, not the API. Accepting it is validating the wrong audience (confused deputy). ([Access tokens](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens), [Claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation))

Minimum bar: API **requires** a validated Entra access token for operator routes; API keys only for non-user automation with a separate principal.

---

## Claim names (concrete)

| Claim | In | Use |
|---|---|---|
| **`oid`** | ID + access (needs `profile` for users) | **Immutable user object ID.** Same across apps in the tenant. **Map to `users`. Graph `id`.** Do not reuse. Different per tenant if the same person is a guest elsewhere. |
| **`tid`** | ID + access (`profile` for access) | **Tenant GUID. Must equal BigTapp. Combine with `oid` as the identity key.** |
| **`iss`** | both | STS + tenant. Exact match to tenant v2 issuer. |
| **`aud`** | ID: SPA client ID. Access: **API** client ID (v2) or App ID URI (v1) | API must require API audience. |
| **`sub`** | both | Pairwise per app. Do **not** join SPA ID token `sub` to API token `sub`. Prefer `oid`. |
| **`scp`** | access (user tokens) | Delegated scopes. Require `access_as_user` (or your name). |
| **`roles`** | ID and/or access if app roles assigned | Optional coarse roles. Not Habibi permissions. |
| **`azp`** | v2 access | Calling client app ID (SPA). |
| **`preferred_username`** | v2 only (`profile`) | Display / login hint. **Mutable. Not authz.** |
| **`email`** | optional / `email` scope; guests often have it | **Not guaranteed correct. Never authz or primary key.** |
| **`upn`** | v1 default; v2 **optional claim** | Display / hint. Changes. Guests: `#EXT#` form. **Not authz.** |
| **`unique_name`** | **v1 only** | Display only. |
| **`idp`** | guests / federation | Home IdP. Do not correlate across tenants. |
| **`ver`** | both | `1.0` or `2.0`. |
| **`name`** | `profile` | Display only. |
| **`groups`** | if configured | GUIDs; overage at 200. |
| **`hd`** | — | **Not issued by Entra.** |

---

## Source list (Microsoft Learn / first-party)

All retrieved **2026-09-08** unless a page states another date.

| URL | Topic |
|---|---|
| https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/saml-vs-oidc-decision-guide | OIDC vs SAML |
| https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/plan-sso-integration-isv | ISV SSO defaults; SPA must OIDC |
| https://learn.microsoft.com/en-us/entra/identity-platform/v2-app-types | SPA PKCE; implicit not recommended |
| https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow | Auth code; PKCE required for SPA; `domain_hint` |
| https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-implicit-grant-flow | Implicit discouraged; `domain_hint` guest note |
| https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc | OIDC; tenant path; `domain_hint`; guests in tenant |
| https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols | OAuth/OIDC roles; tokens |
| https://learn.microsoft.com/en-us/entra/identity-platform/authentication-vs-authorization | AuthN vs AuthZ; OIDC vs SAML |
| https://learn.microsoft.com/en-us/entra/architecture/authenticate-applications-and-users | WS-Fed not for new apps; filter `tid`/`iss` |
| https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps | Single-tenant includes guests |
| https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens | JWT validation, JWKS, v1/v2, client must not parse AT |
| https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference | `oid` `tid` `preferred_username` `email` `sub` |
| https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference | `aud` `scp` `roles` `upn` `azp` groups overage |
| https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation | Never authz on email/UPN; validate tid/aud |
| https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims | Optional `upn`/`email`; group limits |
| https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users | Assignment required; GA exception |
| https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps | App roles vs groups |
| https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-overview | API TenantId; token version; Bearer |
| https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-verification-scope-app-roles | Verify `scp`/`roles`; ACL alternative |
| https://learn.microsoft.com/en-us/entra/identity-platform/scenario-spa-overview | MSAL React/browser |
| https://learn.microsoft.com/en-us/entra/identity-platform/scenario-spa-acquire-token | Silent + popup/redirect; RT 24h mentioned in cookies article |
| https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-single-page-app-sign-in | sessionStorage vs localStorage |
| https://learn.microsoft.com/en-us/entra/identity-platform/reference-third-party-cookies-spas | PKCE; 24h RT; no implicit |
| https://learn.microsoft.com/en-us/entra/identity-platform/msal-js-initializing-client-applications | PCA; sessionStorage cache |
| https://learn.microsoft.com/en-us/entra/identity-platform/msal-overview | MSAL; ADAL ended |
| https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows | Implicit: do not use |
| https://learn.microsoft.com/en-us/entra/msal/javascript/ | msal-browser **v5 active**; v3/v4 not active |
| https://learn.microsoft.com/en-us/entra/msal/javascript/browser/v4-migration | v4 → v5 |
| https://learn.microsoft.com/en-us/entra/msal/python/ | Acquire tokens; not API JWT validation |
| https://learn.microsoft.com/en-us/entra/identity-platform/permissions-consent-overview | Delegated scopes vs user RBAC |
| https://learn.microsoft.com/en-us/entra/identity/app-provisioning/user-provisioning | SCIM vs JIT SAML |
| https://learn.microsoft.com/en-us/entra/external-id/user-properties | `#EXT#` UPN; UserType |
| https://learn.microsoft.com/en-us/entra/external-id/external-identities-overview | Workforce vs External ID; B2C 2025-05-01 |
| https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-conditional-access-users-groups | CA guest targeting |
| https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/tenant-restrictions | Network tenant restrictions (not app domain lock) |
| https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/home-realm-discovery-policy | domain_hint / HRD |
| https://learn.microsoft.com/en-us/entra/fundamentals/new-name | Azure AD → Entra ID |
| https://learn.microsoft.com/en-us/entra/identity-platform/sample-v2-code | Python samples (no FastAPI) |
| https://fastapi.tiangolo.com/reference/security | OpenIdConnect / HTTPBearer stubs |
| https://github.com/AzureAD/microsoft-authentication-library-for-js/releases/tag/msal-browser-v5.21.0 | msal-browser 5.21.0 (2026-09-02) |

---

## Open gaps (not documented as first-party for this stack)

- No Microsoft Learn **FastAPI** Entra middleware (unlike Microsoft.Identity.Web for ASP.NET). Follow JWT validation rules + PyJWT/JWKS; optionally study the Python Azure Functions sample.
- No Entra claim that means “verified domain is `bigtapp.ai`.” Domain membership is a **directory** property; tokens carry `tid`/`oid`/`upn`, not a signed `hd`.
- TanStack Start is not a documented MSAL host; use the SPA (msal-browser / msal-react) pattern in the browser bundle.
