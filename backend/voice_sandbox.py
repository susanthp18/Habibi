"""Voice sandbox session gateway — start/stop/tune + status for Habibi Live mode.

Assumes `python -m voice.bot` is reachable on VOICE_RUNNER_URL (default :7860),
or that the API hosts the pipeline itself (``VOICE_EMBEDDED_HOST=true``).

Session config lives in :mod:`voice_session_store`, which is shared with the
voice worker — see that module for why it is not a local JSON file.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
import uuid
from typing import Any

import httpx

from agent_core import prompt as agent_core_prompt
from agent_core.tuning import merge_tuning_delta, normalize_tuning
import sandbox_runtime
import voice_session_store
from voice_session_store import (  # re-exported: the gateway is the public surface
    SessionStoreUnavailable,
    is_session_id,
    session_path,
)

logger = logging.getLogger(__name__)

_RUNNER_URL = (os.getenv("VOICE_RUNNER_URL") or "http://127.0.0.1:7860").rstrip("/")
# Browser-facing offer URL (Vite proxies /voice-rtc → runner).
_WEBRTC_PUBLIC = (os.getenv("VOICE_WEBRTC_PUBLIC_URL") or "/voice-rtc/api/offer").rstrip("/")
_WEBRTC_OFFER = f"{_RUNNER_URL}/api/offer"


def _offer_url_for(session_id: str) -> str:
    """The browser's offer URL, carrying the session id as a query parameter.

    ``requestData`` alone is not enough. The JS transport posts custom data under
    the camelCase key ``requestData``, but ``pipecat.runner.run``'s ``/api/offer``
    binds the body to the ``SmallWebRTCRequest`` *dataclass*, whose field is
    ``request_data`` — FastAPI does not apply that class's camelCase-tolerant
    ``from_dict``, so the browser's payload is dropped and the bot sees
    ``body=None``. That route does, however, take ``session_id`` as a query
    parameter and threads it into ``runner_args.session_id``, which is the
    channel the stock runner actually honours. We send both: this one works
    today on the standalone runner, and ``requestData`` works on the embedded
    host and on Pipecat's ``/sessions/{id}/api/offer`` proxy.
    """
    base, sep, query = _WEBRTC_PUBLIC.partition("?")
    existing = f"{query}&" if sep and query else ""
    return f"{base}?{existing}session_id={urllib.parse.quote(session_id)}"

__all__ = [
    "SessionStoreUnavailable",
    "is_session_id",
    "patch_session",
    "read_session",
    "session_path",
    "start_voice_sandbox",
    "stop_voice_sandbox",
    "tune_voice_sandbox",
    "voice_status",
    "write_session",
]


def write_session(session_id: str, payload: dict[str, Any]) -> None:
    """Create or replace a session in the shared store."""
    voice_session_store.write(session_id, payload)


def read_session(session_id: str) -> dict[str, Any] | None:
    """The session, or None when it does not exist.

    A malformed id raises ``ValueError`` and a broken backend raises
    ``SessionStoreUnavailable``. Neither collapses into None: reporting a dead
    store as ``voice_session_not_found`` is how a whole broken deployment used
    to hide behind a routine-looking warning.
    """
    return voice_session_store.read(session_id)


def patch_session(session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Atomically merge ``patch`` into one session. None when it is missing."""
    return voice_session_store.mutate(session_id, lambda cur: {**cur, **patch, "updatedAt": time.time()})


def voice_status() -> dict[str, Any]:
    # Embedded host: the pipeline runs in this process, so there is no :7860 to
    # probe. Probing anyway would report the voice runtime as down and every
    # start would 503.
    from voice.host import embedded_host_enabled

    if embedded_host_enabled():
        from voice import admission

        # Capacity is reported ONLY on the embedded path. The counter is
        # process-local (see voice/admission.py), so when the pipeline runs in a
        # separate `voice` container this process's counter is permanently zero
        # — reporting it would be worse than reporting nothing, because it would
        # read as "plenty of headroom" during an overload.
        return {
            "ok": True,
            "webrtcUrl": _WEBRTC_PUBLIC,
            "detail": "embedded host",
            "capacity": admission.snapshot(),
        }
    try:
        with httpx.Client(timeout=1.5) as client:
            for path in ("/status", "/"):
                try:
                    r = client.get(f"{_RUNNER_URL}{path}")
                    if r.status_code < 500:
                        return {
                            "ok": True,
                            "webrtcUrl": _WEBRTC_PUBLIC,
                            "detail": f"runner {r.status_code}",
                        }
                except Exception:
                    continue
    except Exception as exc:
        return {"ok": False, "webrtcUrl": None, "detail": str(exc)}
    return {"ok": False, "webrtcUrl": None, "detail": "voice runner unreachable"}


def _bind_persona_to_customer(persona: dict[str, Any]) -> dict[str, Any]:
    """Make the persona name and the CRM record the same person.

    A persona is free text the tester typed; every CRM tool reads the customers
    table. With nothing joining them the bot legitimately holds two identities
    for one caller — a rehearsal as "Rahul Sharma" verified against phone
    last-4 2324, matched ``cust-susanth``, and the bot switched names mid-call
    and read out that customer's balance.

    When the persona names a ``customerId`` the CRM record wins and its name is
    written back into the persona, so the prompt and the tools cannot disagree.
    An unknown id is dropped rather than honoured: rehearsing against an account
    that does not exist would fail at the first tool call, and silently.
    """
    if not isinstance(persona, dict):
        return {}
    customer_id = str(persona.get("customerId") or "").strip()
    if not customer_id:
        return persona

    try:
        import db

        row = db.get_customer(customer_id)
    except Exception:
        logger.exception("voice sandbox: persona customer lookup failed")
        return persona

    if not row:
        logger.warning(
            "voice sandbox: persona customerId %r not found — leaving persona unbound",
            customer_id,
        )
        bound = dict(persona)
        bound.pop("customerId", None)
        return bound

    bound = dict(persona)
    bound["customerId"] = row.get("id") or customer_id
    bound["name"] = row.get("name") or persona.get("name")
    return bound


def start_voice_sandbox(payload: dict[str, Any]) -> dict[str, Any]:
    status = voice_status()
    if not status.get("ok"):
        raise RuntimeError(status.get("detail") or "voice_runner_unavailable")

    session_id = f"VS-{uuid.uuid4().hex[:10].upper()}"
    tuning = normalize_tuning(payload.get("tuning"))
    prompt_version_id = payload.get("promptVersionId")
    kb_snapshot_id = payload.get("kbSnapshotId")
    scenario_id = payload.get("scenarioId")
    persona = payload.get("persona") if isinstance(payload.get("persona"), dict) else {}
    persona = _bind_persona_to_customer(persona)

    sandbox_run_id = None
    try:
        run = sandbox_runtime.create_sandbox_run(
            {
                "promptVersionId": prompt_version_id,
                "scenarioId": scenario_id,
                "scenarioTitle": scenario_id,
                "kbSnapshotId": kb_snapshot_id,
                "persona": persona,
                "openingTemplate": "",
                "context": {
                    "customer_name": persona.get("name") or "Customer",
                    # Tenant config, not deployment-specific constants — the
                    # sandbox must render the same persona the live bot uses.
                    "agent_name": agent_core_prompt.agent_name(),
                    "bank_name": agent_core_prompt.bank_name(),
                    "language": persona.get("language") or "English",
                },
            }
        )
        sandbox_run_id = run.get("id")
        if not prompt_version_id:
            prompt_version_id = run.get("promptVersionId")
    except Exception:
        logger.exception("voice sandbox: could not create sandbox_run; continuing")

    session = {
        "sessionId": session_id,
        "sandboxRunId": sandbox_run_id,
        "promptVersionId": prompt_version_id,
        "kbSnapshotId": kb_snapshot_id,
        "scenarioId": scenario_id,
        "persona": persona,
        "tuning": tuning,
        "environment": "sandbox",
        "status": "starting",
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "pendingTune": None,
    }
    write_session(session_id, session)
    # Do not write "latest" — concurrent Live sessions race on a shared pointer.
    # The session id reaches the bot on the offer URL (and in requestData); see
    # _offer_url_for.

    return {
        "sessionId": session_id,
        "webrtcUrl": _offer_url_for(session_id),
        "sandboxRunId": sandbox_run_id,
    }


def stop_voice_sandbox(session_id: str) -> dict[str, Any]:
    cur = patch_session(session_id, {"status": "stopped"})
    if not cur:
        raise KeyError(f"voice_session_not_found: {session_id}")
    run_id = cur.get("sandboxRunId")
    if run_id:
        try:
            sandbox_runtime.complete_sandbox_run(run_id)
        except Exception:
            logger.exception("complete sandbox run failed for %s", run_id)
    return {"ok": True, "sessionId": session_id}


def tune_voice_sandbox(session_id: str, tuning_delta: dict[str, Any]) -> dict[str, Any]:
    """Persist a tuning delta for restart / next-call construction.

    Mid-call live apply is the WebRTC data channel
    (``sendClientMessage("tuning_delta", …)`` → ``worker.rtvi``). This HTTP
    route only merges into the session file so a Restart call picks up the
    knobs; it does not push UpdateSettingsFrame to a running worker.
    """
    # Merge inside the store's exclusive section: two concurrent tunes would
    # otherwise both read the pre-merge state and the second write would drop
    # the first delta entirely.
    merged: dict[str, Any] = {}

    def _apply(cur: dict[str, Any]) -> dict[str, Any]:
        nonlocal merged
        merged = merge_tuning_delta(cur.get("tuning") or {}, tuning_delta or {})
        patch: dict[str, Any] = {
            "tuning": merged,
            # pendingTune kept for observability / next-call merge — not polled live.
            "pendingTune": tuning_delta,
            "updatedAt": time.time(),
        }
        # `stopped` is terminal: a tune racing a stop must not resurrect the
        # session as live.
        if (cur.get("status") or "") != "stopped":
            patch["status"] = "live"
        return {**cur, **patch}

    if voice_session_store.mutate(session_id, _apply) is None:
        raise KeyError(f"voice_session_not_found: {session_id}")
    return {"ok": True, "tuning": merged, "apply": "persist"}
