"""Microsoft Entra access-token validation and first-login provision.

Entra authenticates. PayInt authorizes: tokens never carry route permissions.
The identity key is ``oid`` + ``tid``. Email/UPN/name are display only after
the first bind. Guests are refused even when Entra issued a token.
"""

from __future__ import annotations

import base64
import json
import hashlib
import logging
import threading
import time
import uuid
from typing import Any

import jwt
from jwt import PyJWKClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from env_utils import env_str

logger = logging.getLogger(__name__)

MSA_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"
DEFAULT_BOOTSTRAP_UPN = "susanth.p@bigtapp.ai"
SCOPE_NAME = "access_as_user"

_jwks_lock = threading.Lock()
_jwks_client: PyJWKClient | None = None
_jwks_tid: str | None = None
_bearer_lock = threading.Lock()
# token digest -> (monotonic deadline, user_id). Same access token is sent on
# every browser call; locking users and rewriting last_login_at each time is
# what made the console hitch after SSO.
_bearer_cache: dict[str, tuple[float, str]] = {}
_BEARER_CACHE_TTL_S = 30.0
_BEARER_CACHE_MAX = 256


class EntraAuthError(Exception):
    """Token rejected. Middleware maps this to 401 with a generic detail."""


def configured() -> bool:
    return bool(_tenant_id() and _audience())


def looks_like_jwt(token: str) -> bool:
    """True for a three-segment JWT header that names an algorithm.

    API keys must never take this path: a JWT-shaped bearer with Entra unset
    is 401, not a confused-deputy key compare.
    """
    if not token or token.count(".") != 2:
        return False
    header_b64 = token.split(".", 1)[0]
    try:
        padded = header_b64 + "=" * (-len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return False
    return isinstance(header, dict) and bool(header.get("alg"))


def _tenant_id() -> str:
    return env_str("ENTRA_TENANT_ID")


def _audience() -> str:
    return env_str("ENTRA_API_AUDIENCE")


def _accepted_audiences(aud: str) -> list[str]:
    """GUID and App ID URI are both valid ``aud`` values for this API."""
    aud = aud.strip()
    if not aud:
        return []
    if aud.startswith("api://"):
        guid = aud.removeprefix("api://").split("/", 1)[0]
        return [aud, guid] if guid else [aud]
    return [aud, f"api://{aud}"]


def _bootstrap_upns() -> frozenset[str]:
    raw = env_str("ENTRA_BOOTSTRAP_ADMIN_UPNS", DEFAULT_BOOTSTRAP_UPN)
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def _issuer(tid: str) -> str:
    return f"https://login.microsoftonline.com/{tid}/v2.0"


def _jwks(tid: str) -> PyJWKClient:
    global _jwks_client, _jwks_tid
    with _jwks_lock:
        if _jwks_client is not None and _jwks_tid == tid:
            return _jwks_client
        url = f"https://login.microsoftonline.com/{tid}/discovery/v2.0/keys"
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
        _jwks_tid = tid
        return _jwks_client


def _signing_key(token: str, tid: str, override: Any | None) -> Any:
    if override is not None:
        return override
    return _jwks(tid).get_signing_key_from_jwt(token).key


def validate_access_token(token: str, *, signing_key: Any | None = None) -> dict[str, Any]:
    """Return claims for a v2 delegated user token, or raise EntraAuthError."""
    tid = _tenant_id()
    aud = _audience()
    if not tid or not aud:
        raise EntraAuthError("entra_unconfigured")
    if not token:
        raise EntraAuthError("unauthorized")

    try:
        key = _signing_key(token, tid, signing_key)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=_accepted_audiences(aud),
            issuer=_issuer(tid),
            leeway=60,
            options={
                "require": ["exp", "iss", "aud"],
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
        )
    except EntraAuthError:
        raise
    except Exception as exc:
        try:
            unverified = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_exp": False,
                    "verify_iss": False,
                },
            )
            logger.info(
                "entra token rejected: %s aud=%s iss=%s",
                type(exc).__name__,
                unverified.get("aud"),
                unverified.get("iss"),
            )
        except Exception:
            logger.info("entra token rejected: %s", type(exc).__name__)
        raise EntraAuthError("unauthorized") from None

    return _assert_user_token(claims, tid)


def _claim_str(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if value is None:
        return ""
    return str(value).strip()


def _assert_user_token(claims: dict[str, Any], expected_tid: str) -> dict[str, Any]:
    if _claim_str(claims, "ver") != "2.0":
        raise EntraAuthError("unauthorized")
    token_tid = _claim_str(claims, "tid").lower()
    if token_tid != expected_tid.lower() or token_tid == MSA_TENANT_ID:
        raise EntraAuthError("unauthorized")
    if _claim_str(claims, "idtyp").lower() == "app":
        raise EntraAuthError("unauthorized")
    oid = _claim_str(claims, "oid")
    try:
        uuid.UUID(oid)
    except ValueError:
        raise EntraAuthError("unauthorized") from None
    scp = _claim_str(claims, "scp")
    scopes = {s.strip() for s in scp.split() if s.strip()}
    if SCOPE_NAME not in scopes:
        raise EntraAuthError("unauthorized")
    upn = _claim_str(claims, "preferred_username") or _claim_str(claims, "upn")
    acct = claims.get("acct")
    if acct in (1, "1") or "#EXT#" in upn.upper():
        raise EntraAuthError("unauthorized")
    return claims


def resolve_bearer(token: str, *, signing_key: Any | None = None) -> tuple[bool, str | None, str | None]:
    """Validate + provision. Same shape as ``actor_context.resolve_authenticated_actor``."""
    digest = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    now = time.monotonic()
    with _bearer_lock:
        hit = _bearer_cache.get(digest)
        if hit is not None and hit[0] > now:
            return True, hit[1], None
    try:
        claims = validate_access_token(token, signing_key=signing_key)
        user_id = provision_user(claims)
    except EntraAuthError:
        return False, None, "unauthorized"
    except Exception:
        logger.exception("entra provision failed")
        return False, None, "unauthorized"
    if not user_id:
        return False, None, "unauthorized"
    with _bearer_lock:
        if len(_bearer_cache) >= _BEARER_CACHE_MAX:
            _bearer_cache.clear()
        _bearer_cache[digest] = (now + _BEARER_CACHE_TTL_S, user_id)
    return True, user_id, None


def provision_user(claims: dict[str, Any]) -> str:
    """Bind ``oid`` to a users row. Bootstrap Admin, else invite role, else none.

    Uses ``db.engine`` so the ``db_tx`` test proxy wraps the transaction.
    Known users are a read. The advisory lock only serialises first-login
    inserts so two tabs cannot mint two rows for one oid.
    """
    import db
    from db_core import _tenant

    oid = str(uuid.UUID(_claim_str(claims, "oid")))
    tid = _claim_str(claims, "tid")
    upn = _claim_str(claims, "preferred_username") or _claim_str(claims, "upn")
    name = _claim_str(claims, "name") or upn or "Operator"
    tenant_id = _tenant()

    import db_invites

    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, status, name, entra_upn FROM users
                 WHERE entra_oid = CAST(:oid AS uuid)
                """
            ),
            {"oid": oid},
        ).mappings().first()
        if row is not None:
            # Inactive operators still authenticate so GET /me and
            # POST /access-requests work. Grants are emptied in authz
            # unless a pending invite restores them below.
            if (row["name"] or "") != name or (row["entra_upn"] or "") != (upn or "") or str(
                row["status"] or ""
            ) != "active":
                conn.execute(
                    text(
                        """
                        UPDATE users
                           SET name = :name,
                               entra_upn = :upn,
                               entra_tid = CAST(:tid AS uuid),
                               last_login_at = now(),
                               updated_at = now()
                         WHERE id = :id
                        """
                    ),
                    {"id": row["id"], "name": name, "upn": upn or None, "tid": tid},
                )
            invited = db_invites.consume_pending_invite(conn, tenant_id, upn)
            if invited:
                db_invites.apply_invite_role(
                    conn,
                    str(row["id"]),
                    invited,
                    activate=str(row["status"] or "") != "active",
                )
                import authz

                authz.invalidate_permission_cache(str(row["id"]))
            return str(row["id"])

        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"entra-oid:{oid}"},
        )
        raced = conn.execute(
            text("SELECT id, status FROM users WHERE entra_oid = CAST(:oid AS uuid)"),
            {"oid": oid},
        ).mappings().first()
        if raced is not None:
            return str(raced["id"])

        bootstrap = upn.lower() in _bootstrap_upns()
        user_id = oid
        nested = conn.begin_nested()
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO users (
                        id, tenant_id, name, email, status,
                        entra_oid, entra_tid, entra_upn, bootstrap_admin,
                        last_login_at
                    ) VALUES (
                        :id, :tenant, :name, :email, 'active',
                        CAST(:oid AS uuid), CAST(:tid AS uuid), :upn, :boot,
                        now()
                    )
                    """
                ),
                {
                    "id": user_id,
                    "tenant": tenant_id,
                    "name": name,
                    "email": upn or None,
                    "oid": oid,
                    "tid": tid,
                    "upn": upn or None,
                    "boot": bootstrap,
                },
            )
            nested.commit()
        except IntegrityError:
            nested.rollback()
            existing = conn.execute(
                text("SELECT id FROM users WHERE entra_oid = CAST(:oid AS uuid)"),
                {"oid": oid},
            ).mappings().first()
            if existing is None:
                raise EntraAuthError("unauthorized") from None
            return str(existing["id"])

        # Uninvited first login gets a users row and no role. The console
        # then asks them to request access; an admin grants a role.
        role_wanted = "role-admin" if bootstrap else None
        invited = db_invites.consume_pending_invite(conn, tenant_id, upn)
        if invited and not bootstrap:
            role_wanted = invited
        if role_wanted:
            role_id = _role_id(conn, tenant_id, role_wanted)
            if role_id:
                conn.execute(
                    text(
                        """
                        INSERT INTO user_roles (user_id, role_id)
                        VALUES (:uid, :rid)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"uid": user_id, "rid": role_id},
                )
        return user_id


def _role_id(conn: Any, tenant_id: str, wanted: str) -> str | None:
    """Resolve a stock role by id, then by name. Insert Viewer if missing."""
    names = {
        "role-admin": "Admin",
        "role-viewer": "Viewer",
    }
    row = conn.execute(
        text(
            """
            SELECT id FROM roles
             WHERE tenant_id = :t AND (id = :id OR lower(name) = lower(:name))
             LIMIT 1
            """
        ),
        {"t": tenant_id, "id": wanted, "name": names.get(wanted, wanted)},
    ).mappings().first()
    if row is not None:
        return str(row["id"])
    if wanted != "role-viewer":
        return None
    conn.execute(
        text(
            """
            INSERT INTO roles (id, tenant_id, name)
            VALUES (:id, :t, 'Viewer')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": wanted, "t": tenant_id},
    )
    return wanted
