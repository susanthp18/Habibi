"""Voice sandbox session gateway — start/stop/tune + status for Habibi Live mode.

v1: assumes `python -m voice.bot` runner is up on VOICE_RUNNER_URL (default :7860).
Session config is written to a JSON file the worker can read.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from agent_core.tuning import merge_tuning_delta, normalize_tuning
import sandbox_runtime

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path(__file__).resolve().parent / ".cache" / "voice_sandbox_sessions"
_RUNNER_URL = (os.getenv("VOICE_RUNNER_URL") or "http://127.0.0.1:7860").rstrip("/")
# Browser-facing offer URL (Vite proxies /voice-rtc → runner).
_WEBRTC_PUBLIC = (os.getenv("VOICE_WEBRTC_PUBLIC_URL") or "/voice-rtc/api/offer").rstrip()
_WEBRTC_OFFER = f"{_RUNNER_URL}/api/offer"


def _ensure_dir() -> None:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def session_path(session_id: str) -> Path:
    return _SESSIONS_DIR / f"{session_id}.json"


def write_session(session_id: str, payload: dict[str, Any]) -> None:
    _ensure_dir()
    path = session_path(session_id)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_session(session_id: str) -> dict[str, Any] | None:
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("failed to read voice sandbox session %s", session_id)
        return None


def patch_session(session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    cur = read_session(session_id)
    if not cur:
        return None
    cur.update(patch)
    cur["updatedAt"] = time.time()
    write_session(session_id, cur)
    return cur


def voice_status() -> dict[str, Any]:
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
                    "agent_name": "Priya",
                    "bank_name": "HDFC Bank",
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
    write_session("latest", session)

    return {
        "sessionId": session_id,
        "webrtcUrl": _WEBRTC_PUBLIC,
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
    cur = read_session(session_id)
    if not cur:
        raise KeyError(f"voice_session_not_found: {session_id}")
    merged = merge_tuning_delta(cur.get("tuning") or {}, tuning_delta or {})
    # pendingTune kept for observability / next-call merge only — not polled live.
    patch_session(session_id, {"tuning": merged, "pendingTune": tuning_delta, "status": "live"})
    write_session("latest", read_session(session_id) or {})
    return {"ok": True, "tuning": merged, "apply": "persist"}
