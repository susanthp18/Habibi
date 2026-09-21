"""Helpers every router shares: the write-error mapping and the upload cap.

Moved out of main.py so the routers can import them without importing the
app -- main.py includes the routers, so the other direction would be a cycle.
"""

from __future__ import annotations

import logging
from typing import Any
from env_utils import env_int

import authz
import observability

from fastapi import Depends, HTTPException, Request, Response
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection
from starlette.concurrency import run_in_threadpool

import pg_errors

logger = logging.getLogger("main")


async def authz_guard(conn: HTTPConnection) -> None:
    """Per-route permission check, applied to every route in the app.

    Registered as a global dependency rather than 180 per-route ``Depends``
    arguments so the policy is one reviewable table (``authz.ROUTE_PERMISSIONS``)
    and so ``tests/test_authz.py`` can prove it covers the whole route table — a
    forgotten ``Depends`` is silent, a missing registry row is a test failure.

    Dependencies resolve after routing, so ``scope["route"].path`` is the path
    *template* (``/customers/{customer_id}``), which is what the registry keys
    on. Falling back to the raw path would mean a parameterised route never
    matches and is therefore denied — the safe direction, but useless.

    The parameter is an ``HTTPConnection`` — the base class of both ``Request``
    and ``WebSocket`` — because "every route in the app" includes the two
    websocket ones. Annotated ``Request``, this did not quietly skip sockets:
    FastAPI cannot build a ``Request`` from a websocket scope, so the dependency
    solver raised ``TypeError`` and rejected the upgrade with a 500. Twilio's
    Media Stream never connected, the customer heard silence, and every status
    callback still reported a healthy call.
    """
    # A socket has no method, and the registry is keyed on one. The two
    # websocket routes authorise themselves with ``VOICE_WS_PROXY_SECRET``
    # (`_voice_ws_upgrade_authorized`, fail-closed in every environment) — that
    # is the design, not an oversight. ``tests/test_voice_ws_authz.py`` pins the
    # route list so a websocket added later cannot inherit this exemption in
    # silence.
    if conn.scope.get("type") != "http":
        return

    route = conn.scope.get("route")
    path_template = getattr(route, "path", None) or conn.url.path
    method = conn.scope.get("method", "")
    # Only an actor the auth middleware actually authenticated counts. Not
    # actor_context.get_actor_user_id(), which falls back to the process default
    # — that would hand an unauthenticated caller the default user's grants.
    actor = getattr(conn.state, "actor_user_id", None)
    try:
        # On a grant-cache miss `check` reads Postgres; off the event loop, or
        # every request in flight waits on that one connection.
        await run_in_threadpool(authz.check, method, path_template, actor)
    except authz.PermissionDenied as exc:
        logger.warning(
            "authz denied actor=%s %s %s (needs %s)",
            actor, method, path_template, exc.permission,
        )
        observability.observe_authz_denial(route=path_template, permission=exc.permission)
        raise HTTPException(status_code=403, detail=f"forbidden:{exc.permission}") from exc

#: Whether the Pipecat pipeline runs in this process (VOICE_EMBEDDED_HOST).
#: Read once at import: the telephony router and main's auth-exempt list both
#: branch on it.
try:
    from voice.host import embedded_host_enabled as _embedded_host_enabled

    EMBEDDED_VOICE_HOST = _embedded_host_enabled()
except Exception:  # pragma: no cover - optional voice extras
    EMBEDDED_VOICE_HOST = False


class Utf8JSONResponse(JSONResponse):
    """JSON responses that state their encoding instead of assuming it is obvious.

    Starlette only appends ``charset`` to ``text/*`` media types, so every
    response here went out as a bare ``application/json``. RFC 8259 makes UTF-8
    mandatory for JSON exchanged between systems, so that is not *wrong* — but a
    charset nobody states is a charset every client is free to guess, and a
    significant number of them guess ISO-8859-1.

    That is not hypothetical. Windows PowerShell 5.1's ``Invoke-RestMethod`` —
    the default HTTP client on the machines this is operated from — decodes a
    charset-less response as ISO-8859-1, which turns the three correct UTF-8
    bytes of an em dash into the three characters U+00E2 U+0080 U+0094. An audit
    of the skill catalog did exactly that and reported permanent mojibake inside
    a signed first-party pack, with the contentHash and signature said to cover
    the corrupt bytes. Two rounds of investigation went into a repair migration
    for data that was never damaged: the database, the disk and the wire all
    held U+2014 the whole time, and only the reader disagreed.

    For a product whose content is largely Hindi, Tamil, Telugu, Kannada,
    Marathi and Bengali, a client that silently mangles every non-ASCII
    character is not a curiosity. Nine bytes of header removes the ambiguity.
    """

    media_type = "application/json; charset=utf-8"


# Cap multipart uploads (STT / KB) — reject before buffering unbounded bytes.
_MAX_UPLOAD_BYTES = env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024)

async def _read_upload_capped(file: UploadFile, *, max_bytes: int | None = None) -> bytes:
    limit = max_bytes if max_bytes is not None else _MAX_UPLOAD_BYTES
    buf = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(status_code=413, detail="upload_too_large")
    return bytes(buf)

# ValueError is two kinds of thing on this funnel: the client sent garbage
# (`bot_id_required`, `empty_message`) and someone else got there first
# (`publish_conflict`, `handoff_already_claimed`). Unmapped codes stay 409 so
# today's wire is the default; each other status is opt-in per code. Prefixed
# messages (`invalid_reason: foo`) match on the token before the first colon.
# English sentences that are validation, not codes, are keys here too —
# `detail=str(exc)` is the public contract and renaming them is a wire change.
_VALUE_ERROR_STATUS: dict[str, int] = {
    "bot_id_required": 422,
    "empty_message": 422,
    "invalid_severity": 422,
    "invalid_updated_after": 422,
    "disclosure_label_required": 422,
    "productId_required": 422,
    "loss_reason_required": 422,
    "target_bot_required": 422,
    "channels_required": 422,
    "confirm_required": 422,
    "skill_slug_required": 422,
    "skill_slug_invalid": 422,
    "allowed_tools_must_be_list": 422,
    "skill_missing_frontmatter": 422,
    "skill_missing_name": 422,
    "skill_allowed_tools_not_a_list": 422,
    "connector_url_required": 422,
    "connector_url_https_only": 422,
    "connector_url_unresolvable": 422,
    "connector_slug_required": 422,
    "connector_data_class_required": 422,
    "connector_data_class_unknown": 422,
    "cimd_issuer_https_only": 422,
    "connector_prefix_must_be_ext": 422,
    "vault_secret_required": 422,
    "vault_name_required": 422,
    "mcp_scopes_required": 422,
    "a2a_cert_required": 422,
    "a2a_signal_unknown": 422,
    "clone_source_required": 422,
    "unknown_clone_template": 422,
    "agent_required": 422,
    "unknown_role": 422,
    "last_admin": 409,
    "bootstrap_admin_protected": 409,
    "already_signed_in": 409,
    "invite_not_pending": 409,
    "already_pending": 409,
    "request_not_pending": 409,
    "access_requests_unavailable": 503,
    "actor_required": 422,
    "invalid_path": 422,
    "invalid_permission": 422,
    "invalid_email": 422,
    "smtp_failed": 502,
    "title_required": 422,
    "accepted_required": 422,
    "record_ids_required": 422,
    "actor_email_missing": 422,
    "when_must_be_list": 422,
    "then_must_be_object": 422,
    "no_fields": 422,
    "invalid_reason": 422,
    "invalid_disposition": 422,
    "invalid_reminder_status": 422,
    "invalid_status": 422,
    "invalid_coaching_status": 422,
    "invalid_calibration_status": 422,
    "invalid_format": 422,
    "invalid_export_status": 422,
    "invalid_kind": 422,
    "invalid_source": 422,
    "invalid_presence_status": 422,
    "invalid_channel": 422,
    "invalid_range": 422,
    "invalid_purge_scope": 422,
    "provide either ownerUserId or ownerBotId, not both": 422,
    "note text is required": 422,
    "channel status or optedIn is required": 422,
    "set subjectUserId or subjectBotId, not both": 422,
    "invalid status": 422,
    "entries require criterionId": 422,
}

def _handle_write(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        # `str(KeyError("x"))` is `"'x'"` — the repr, not the message. It reached
        # the UI verbatim, so an Archive that lost a race toasted the operator
        # `'agent_card_not_found_or_archived:sweep-probe'`, stray quotes and all.
        detail = str(exc.args[0]) if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status = _VALUE_ERROR_STATUS.get(detail)
        if status is None:
            status = _VALUE_ERROR_STATUS.get(detail.split(":", 1)[0].strip(), 409)
        raise HTTPException(status_code=status, detail=detail) from exc
    except IntegrityError as exc:
        # A bad foreign key (unknown productId / teamId / ownerUserId) is a
        # client error, not a server fault. It used to escape as an unhandled
        # 500 with a psycopg traceback in the response body. The detail names
        # the class -- duplicate, unknown_reference, check_violation -- from
        # the SQLSTATE, one map for every write path.
        logger.warning("write rejected by a database constraint: %s", exc.orig)
        raise HTTPException(status_code=409, detail=pg_errors.constraint_detail(exc)) from exc


def _unavailable(status: int, detail: str, retry_after_s: float) -> Utf8JSONResponse:
    """A 429/503 with the one header a client can act on."""
    import math

    return Utf8JSONResponse(
        status_code=status,
        content={"detail": detail},
        headers={"Retry-After": str(max(1, math.ceil(retry_after_s)))},
    )


def register_error_handlers(app: Any) -> None:
    """Every error the API answers, in one place.

    FastAPI builds HTTPException and validation responses with its own
    JSONResponse, so those went out as bare application/json; the stock
    handlers are kept and one header rewritten. The 422 body is rebuilt
    without pydantic's ``input`` echo: the field that failed validation is
    the field most likely to hold a PAN or a phone number, and it went back
    to the client verbatim. 429 and 503 carry Retry-After. A true 500 gets
    one envelope with the request id -- Starlette runs the catch-all inside
    ServerErrorMiddleware, outside every BaseHTTPMiddleware, so the
    request-id middleware never sees that response and this sets the header
    itself.
    """
    from fastapi.exception_handlers import http_exception_handler
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    import azure_openai
    import circuit_breaker
    import kb_rate_limit

    async def _json_charset(response: Response) -> Response:
        media = response.headers.get("content-type", "")
        if media.startswith("application/json") and "charset=" not in media.lower():
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return await _json_charset(await http_exception_handler(request, exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        errors = [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]
        return Utf8JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(azure_openai.AzureBusyError)
    async def _busy(_request: Request, exc: azure_openai.AzureBusyError):
        return _unavailable(503, str(exc) or "azure_concurrency_saturated", azure_openai._acquire_timeout_s())

    @app.exception_handler(circuit_breaker.CircuitOpenError)
    async def _circuit(_request: Request, exc: circuit_breaker.CircuitOpenError):
        return _unavailable(503, str(exc) or "circuit_open", exc.retry_after_s)

    @app.exception_handler(kb_rate_limit.RateLimitExceeded)
    async def _rate(_request: Request, exc: kb_rate_limit.RateLimitExceeded):
        import time

        return _unavailable(429, str(exc) or "rate_limited", 60 - int(time.time()) % 60)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, _exc: Exception):
        rid = getattr(request.state, "request_id", None)
        logger.exception("unhandled %s %s request_id=%s", request.method, request.url.path, rid)
        return Utf8JSONResponse(
            status_code=500,
            content={"detail": "internal_error", "requestId": rid},
            headers={"X-Request-Id": rid} if rid else None,
        )


#: Every router declares this dependency. Routes are appended to the app flat
#: (see main.py), which bypasses the app-level `dependencies=[...]` an
#: `include_router` would have merged -- so the guard travels with the route.
ROUTER_DEPENDENCIES = [Depends(authz_guard)]
