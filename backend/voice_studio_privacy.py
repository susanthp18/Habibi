"""What an agent builder sees of a Voice Studio run without raw-PII permission.

The engine's run views (the run page, the runs lists) carry the conversation as
spoken -- card numbers, OTPs, names -- and the caller's number. Building and
debugging an agent needs the conversation's shape, not a customer's data, so
the gateway passes run payloads through here for anyone without
``PII_RAW_READ``:

* a filed call's turns are replaced by PayInt's stored transcript, which the
  call-intelligence pass masked (the same text Audit shows);
* anything else (an unfiled or test run) is masked by the validated-pattern
  detectors of ``call_intel.pii`` -- spoken digits, secrets after an OTP or
  PIN question, cards, IDs -- and the at-rest regex;
* the caller's name and numbers in the run's context are masked.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text

#: Context keys that identify the customer.
_IDENTITY_KEYS = frozenset({
    "customer_name", "first_name", "phone_number", "caller_number", "called_number", "to_number",
    "from_number", "account_tail", "email",
})
#: Engine paths whose JSON is a run or a page of runs.
RUN_DETAIL = re.compile(r"^/workflow/\d+/runs/\d+$")
RUN_LISTS = (re.compile(r"^/organizations/usage/runs$"), re.compile(r"^/workflow/\d+/runs$"),
             re.compile(r"^/campaign/\d+/runs$"), re.compile(r"^/organizations/reports/daily/runs$"))


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        digits = re.sub(r"\D", "", value)
        return f"•••{digits[-2:]}" if len(digits) >= 6 else "•••"
    return value


def _mask_context(ctx: Any) -> Any:
    if not isinstance(ctx, dict):
        return ctx
    return {k: (_mask_value(v) if k in _IDENTITY_KEYS and v not in (None, "") else v) for k, v in ctx.items()}


def _stored_turns(run_id: Any) -> list[str] | None:
    """PayInt's masked transcript of a filed run, in turn order."""
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT t.text FROM voice_sessions s JOIN interaction_transcript t "
                 "ON t.interaction_id = s.interaction_id WHERE s.id = :sid ORDER BY t.turn_index"),
            {"sid": f"VS-studio-{run_id}"},
        ).scalars().all()
    return list(rows) or None


def _pattern_masked(events: list[dict[str, Any]]) -> list[str]:
    from call_intel import pii
    import pii_redact
    import voice_studio

    turns = [pii.Turn(i, "bot" if e["type"] == "rtf-bot-text" else "customer", voice_studio.spoken_text(e))
             for i, e in enumerate(events)]
    found = pii.detect(turns)
    return [pii_redact.redact_text(pii.masked_text(t.text, [f for f in found if f.turn_index == t.index]))
            for t in turns]


def mask_run(run: dict[str, Any]) -> dict[str, Any]:
    import pii_redact
    import voice_studio

    run = dict(run)
    for key in ("initial_context", "gathered_context"):
        if key in run:
            run[key] = _mask_context(run[key])
    for key in ("caller_number", "called_number", "phone_number"):
        if run.get(key):
            run[key] = _mask_value(run[key])
    logs = run.get("logs")
    if isinstance(logs, dict) and isinstance(logs.get("realtime_feedback_events"), list):
        events = [dict(e) for e in logs["realtime_feedback_events"]]
        spoken = voice_studio.transcript_events(events)
        masked = _stored_turns(run.get("id"))
        if masked is None or len(masked) != len(spoken):
            masked = _pattern_masked(spoken)
        by_identity = {id(e): m for e, m in zip(spoken, masked)}
        out = []
        for e in events:
            payload = dict(e.get("payload") or {})
            if id(e) in by_identity:
                payload["text"] = by_identity[id(e)]
            elif e.get("type") == "rtf-user-transcription" and payload.get("text"):
                payload["text"] = pii_redact.redact_text(str(payload["text"]))  # interim results
            for field in ("arguments", "result"):
                if field in payload:
                    # Tool calls carry what the customer said and what the CRM returned.
                    payload[field] = pii_redact.redact_text(json.dumps(payload[field], default=str))
            out.append({**e, "payload": payload})
        run["logs"] = {**logs, "realtime_feedback_events": out}
    # The raw text transcript and recordings are not signed for this viewer.
    run["transcript_public_url"] = run["recording_public_url"] = None
    run["user_recording_public_url"] = run["bot_recording_public_url"] = None
    return run


def mask_payload(engine_path: str, body: bytes) -> bytes:
    """The run JSON at ``engine_path`` with personal data masked."""
    data = json.loads(body or b"null")
    if RUN_DETAIL.match(engine_path) and isinstance(data, dict):
        data = mask_run(data)
    elif isinstance(data, dict) and isinstance(data.get("runs"), list):
        data = {**data, "runs": [mask_run(r) if isinstance(r, dict) else r for r in data["runs"]]}
    elif isinstance(data, list):
        data = [mask_run(r) if isinstance(r, dict) else r for r in data]
    return json.dumps(data, default=str).encode()


def needs_masking(method: str, engine_path: str) -> bool:
    return method == "GET" and (bool(RUN_DETAIL.match(engine_path)) or any(p.match(engine_path) for p in RUN_LISTS))

