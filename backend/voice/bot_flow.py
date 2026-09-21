"""Which card answers, and the conversation it runs -- the flow half of run_bot.

A pure move out of :mod:`voice.bot`: the sandbox/production bundle resolution,
the mission briefing, the mouth grant and the authored-graph compile, and the
FlowManager. Each step reads and writes the per-call namespace that
:func:`voice.bot.run_bot` threads through its three halves.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from functools import partial
from typing import Any

from loguru import logger

from agent_core import default_context, default_tuning, load_active_bundle
from prompt_render import render_system_prompt, strip_unrendered_crm_tokens
from voice.crm_sink import CrmSink
from voice.natural import build_voice_system_prompt
from voice.session import VoiceSession
from agent_core.dicts import sub


def resolve_call_direction(session, bundle: dict | None = None) -> str:
    """Outbound vs inbound for live QA / CRM. Stream params carry ``call_type``."""
    extra = session.extra if isinstance(getattr(session, "extra", None), dict) else {}
    existing = str(extra.get("call_direction") or "").strip().lower()
    if existing in {"inbound", "outbound"}:
        return existing
    params = extra.get("twilio_params") if isinstance(extra.get("twilio_params"), dict) else {}
    bundle = bundle if isinstance(bundle, dict) else {}
    # Truncated HABIBI_CTX used to default inbound and skip the RBI hours check.
    invalid = str(params.get("ctx_invalid") or extra.get("ctx_invalid") or "").strip().lower()
    if invalid in {"1", "true", "yes"}:
        return "outbound"
    raw = str(
        params.get("call_type")
        or extra.get("call_type")
        or bundle.get("callDirection")
        or ""
    ).strip().lower()
    return "outbound" if raw == "outbound" else "inbound"


def _persona_context(bundle: dict) -> dict[str, str]:
    """Operator-token values this card implies, for the system-prompt render.

    Only ``{language}`` is card-dependent; ``{agent_name}`` and ``{bank_name}``
    are tenant environment and ``{time_of_day}`` is the clock. It exists as a
    function because the previous arrangement — an optional ``context``
    parameter that the one caller never passed — meant every voice call
    substituted ``default_context``'s ``"English"`` no matter what the Persona
    tab said. Deriving the context from the bundle removes the opportunity to
    forget rather than adding a caller who must remember.
    """
    persona = sub(bundle, "persona")
    name = str(persona.get("language") or "").strip()
    return {"language": name} if name else {}


def _system_instruction_from_bundle(bundle: dict, context: dict | None = None) -> str:
    """Lean voice system prompt — authored prompt + persona + guardrails + voice rules.

    ``context`` overlays the card's own values, for callers (tests, the sandbox)
    that need to pin a token.
    """
    ctx = default_context({**_persona_context(bundle), **(context or {})})
    # System policy takes operator tokens only. This used to call render_prompt,
    # which substitutes CRM fields straight into the system string — the one
    # thing prompt_render.py exists to prevent, and the reason the call-start
    # defaults leaked out as "account XXXX". The real values reach the model on
    # the untrusted developer card (ctx.crm_card_message), refreshed as the call
    # learns who it is talking to, so nothing is lost by leaving them out here.
    rendered = render_system_prompt(bundle.get("prompt") or "", ctx)
    rendered = strip_unrendered_crm_tokens(rendered)
    prompt = build_voice_system_prompt(
        rendered,
        bundle.get("guardrails") or {},
        persona=bundle.get("persona") if isinstance(bundle.get("persona"), dict) else None,
    )
    from agent_core.skills.runtime import resolve_mouth

    prefix = resolve_mouth(
        bundle.get("agentCard") or {},
        frozen_connector_tools=bundle.get("frozenTools"),
    ).prompt().prefix
    if prefix:
        prompt = prompt.rstrip() + "\n\n" + prefix
    return prompt


def _sandbox_session_id_from(runner_args, is_session_id) -> str | None:
    """Pull the Sandbox Live session id out of the transport's request data.

    The browser sends it as SmallWebRTC ``requestData``, which the runner puts on
    ``runner_args.body``; the ``/start`` runner path nests the same dict one level
    deeper under ``body``, and a client that posts raw JSON leaves it a string.
    All three shapes are accepted.

    ``runner_args.session_id`` is deliberately *validated*, not trusted: the
    embedded host (:mod:`voice.host`) sets it to our ``VS-`` id, but the
    standalone ``pipecat.runner`` mints ``str(uuid4())`` for every offer. Taking
    that as a sandbox id raised ``invalid_session_id`` on every single call and
    dropped the whole Live configuration.
    """
    body = getattr(runner_args, "body", None)
    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            body = None

    seen: list[str] = []
    for source in (body, (body or {}).get("body") if isinstance(body, dict) else None):
        if not isinstance(source, dict):
            continue
        for key in ("sessionId", "session_id"):
            value = source.get(key)
            if isinstance(value, str) and value:
                seen.append(value)

    transport_sid = getattr(runner_args, "session_id", None)
    if isinstance(transport_sid, str) and transport_sid:
        seen.append(transport_sid)

    for candidate in seen:
        if is_session_id(candidate):
            return candidate
    if seen:
        # A non-canonical id here is a client bug worth naming, not silence.
        logger.warning(
            "ignoring non-sandbox session identifiers on this connection: {}",
            ", ".join(sorted(set(seen))),
        )
    return None


def _attempt_cohort(attempt_id: str) -> dict[str, Any] | None:
    """Blocking call_attempts read — run under ``asyncio.to_thread``."""
    import db as _db
    from sqlalchemy import text as _sql_text

    with _db.engine.connect() as _conn:
        return _db._one(
            _conn.execute(
                _sql_text("SELECT customer_id, bot_id FROM call_attempts WHERE id = :id"),
                {"id": attempt_id},
            )
        )


def _caller_match(ani: str) -> dict[str, Any] | None:
    """Blocking ANI lookup — run under ``asyncio.to_thread``."""
    from voice import twilio_ops

    return twilio_ops.lookup_customer_for_caller(ani)


def _entry_bot(address: str | None) -> str | None:
    """Blocking door/env entry resolve — run under ``asyncio.to_thread``."""
    from agent_core.cards.routing import resolve_entry

    return resolve_entry("voice", address=address)


def _load_mission_row(attempt_id: str) -> dict[str, Any] | None:
    """Blocking mission read — run under ``asyncio.to_thread``."""
    import db as _db
    import mission as mission_mod

    with _db.engine.connect() as conn:
        return mission_mod.load(conn, str(attempt_id))


def _attach_transport(call) -> tuple[Any, bool, str | None]:
    """Transport flags and the sandbox session, if this call has one."""
    runner_args = call.runner_args
    sandbox_session = None
    _store = None
    call_data = getattr(runner_args, "call_data", None)
    transport_type = (
        getattr(runner_args, "transport_type", None)
        or getattr(call_data, "provider", None)
        or ""
    )
    if not transport_type and call_data is not None:
        transport_type = "twilio"
    transport_key = str(transport_type or "").lower()
    is_asterisk = transport_key == "asterisk"
    is_twilio = transport_key in {"twilio", "telnyx", "plivo", "exotel"} or is_asterisk
    call.transport_type = transport_key or None
    call.is_asterisk = is_asterisk
    sandbox_load_error: str | None = None
    try:
        import voice_session_store as _store
    except Exception:
        logger.exception("voice session store unimportable — Live config unavailable")
        sandbox_load_error = "store_unimportable"

    if _store is not None:
        sid = _sandbox_session_id_from(runner_args, _store.is_session_id)
        if sid:
            try:
                sandbox_session = _store.read(sid)
                if not sandbox_session:
                    sandbox_load_error = "session_not_found"
                    logger.error(
                        "voice sandbox session {} not found in {} store — Live call will "
                        "run with the production bundle, not the sandbox config",
                        sid,
                        _store.backend(),
                    )
            except _store.SessionStoreUnavailable:
                sandbox_load_error = "store_unavailable"
                logger.exception("voice sandbox session store unavailable for {}", sid)
            except ValueError:
                sandbox_load_error = "invalid_session_id"
                logger.exception("rejected malformed sandbox session id {}", sid)
        elif not is_twilio:
            sandbox_load_error = "no_session_id"
            logger.warning(
                "No sandbox sessionId in the WebRTC offer — the client must connect with "
                "webrtcRequestParams.requestData = {{sessionId}}. Falling back to the "
                "production bundle; persona / KB snapshot / tuning will not apply."
            )
    call._store = _store
    return sandbox_session, is_twilio, sandbox_load_error


async def resolve_call(call) -> None:
    """Sandbox session, caller cohort, bundle, session, sink, system prompt."""
    import db as _db

    runner_args = call.runner_args
    sandbox_session, is_twilio, sandbox_load_error = _attach_transport(call)
    call_data = getattr(runner_args, "call_data", None)

    # Prefer Sandbox Live session config (written by POST /voice/sandbox/start).
    # Session id arrives via SmallWebRTC request_data → runner_args.body. Never
    # use a shared "latest" pointer — that races between concurrent calls.

    # Resolve caller identity BEFORE canary selection. Loading the bundle first
    # with no customer_id used to send every unmatched inbound call to the
    # canary. Outbound attempts already know the customer and the mouth.
    cohort_customer_id: str | None = None
    cohort_bot_id: str | None = None
    pre_from_number: str | None = None
    #: The dialled leg. Routing reads this and never the caller: which card
    #: answers must not depend on a CRM lookup, and
    #: `twilio_ops.lookup_customer_for_caller` sits under a bare `except`, so
    #: letting it choose would turn one flaky query into "a different agent
    #: answered the phone". Pulled out here rather than at :532 because the
    #: entry decision happens before the session exists.
    pre_to_number: str | None = None
    pre_attempt_id: str | None = None
    if call_data is not None:
        pre_from_number = getattr(call_data, "from_number", None) or (
            call_data.get("from") if isinstance(call_data, dict) else None
        )
        pre_to_number = getattr(call_data, "to_number", None) or (
            call_data.get("to") if isinstance(call_data, dict) else None
        )
        body_params = getattr(call_data, "body", None) or {}
        if isinstance(body_params, dict):
            pre_from_number = pre_from_number or body_params.get("from")
            pre_to_number = pre_to_number or body_params.get("to")
            if str(body_params.get("call_type") or "").strip().lower() == "outbound":
                pre_attempt_id = str(body_params.get("attempt_id") or "").strip() or None
    if pre_attempt_id:
        # Overlap the mission briefing I/O with the rest of setup. load_mission
        # only awaits this task and validates the contract; treatment still
        # fail-closed before speech.
        call._mission_io_task = asyncio.create_task(
            asyncio.to_thread(_load_mission_row, pre_attempt_id)
        )
        try:
            attempt_row = await asyncio.to_thread(_attempt_cohort, pre_attempt_id)
            if attempt_row:
                cohort_customer_id = attempt_row.get("customer_id")
                cohort_bot_id = attempt_row.get("bot_id")
        except Exception:
            logger.exception("outbound attempt lookup failed for canary cohort")
    caller_match: dict[str, Any] | None = None

    async def _maybe_caller() -> None:
        nonlocal caller_match, cohort_customer_id
        if cohort_customer_id is not None or not (is_twilio and pre_from_number):
            return
        try:
            caller_match = await asyncio.to_thread(_caller_match, pre_from_number)
            if caller_match:
                cohort_customer_id = caller_match.get("customerId")
        except Exception:
            logger.exception("Twilio caller lookup failed before bundle load")

    async def _maybe_entry() -> None:
        nonlocal cohort_bot_id
        if cohort_bot_id is not None:
            return
        try:
            # With DOOR_ENABLED unset this is the old env lookup exactly:
            # `resolve_entry` falls back to it on the flag, on the table being
            # absent, and on no row matching. Reversal is unsetting the flag --
            # no restart, no data to undo.
            cohort_bot_id = await asyncio.to_thread(_entry_bot, pre_to_number)
        except Exception:
            cohort_bot_id = None

    await asyncio.gather(_maybe_caller(), _maybe_entry())
    # Hash on ANI when the caller is unmatched so the split stays deterministic
    # without sending every unknown number to the canary.
    cohort_key = cohort_customer_id or pre_from_number

    try:
        if sandbox_session and sandbox_session.get("promptVersionId"):
            from agent_core.deployment import resolve_prompt_bundle

            # to_thread like every neighbouring read above. Both bundle loads
            # are several DB round trips plus a full CompiledBundle validation
            # and a hash recompute; run bare on the loop they are the caller's
            # own silence in the standalone runner, and under
            # VOICE_EMBEDDED_HOST they stall every other live call's audio task.
            bundle = await asyncio.to_thread(
                partial(
                    resolve_prompt_bundle,
                    prompt_version_id=sandbox_session["promptVersionId"],
                    environment="sandbox",
                    fallback_environments=("production",),
                )
            )
            # Prefer version tuning when present; session tuning overlays.
            ver_tuning = (bundle.get("promptVersion") or {}).get("tuning")
            if isinstance(ver_tuning, dict) and ver_tuning:
                from agent_core.tuning import normalize_tuning

                bundle["tuning"] = normalize_tuning(ver_tuning)
            if sandbox_session.get("tuning"):
                from agent_core.tuning import merge_tuning_delta

                bundle["tuning"] = merge_tuning_delta(
                    bundle.get("tuning") or default_tuning(),
                    sandbox_session["tuning"],
                )
            if sandbox_session.get("kbSnapshotId"):
                bundle["kbSnapshotId"] = sandbox_session["kbSnapshotId"]
        else:
            # ChannelNotAuthored is a RuntimeError, not a KeyError: it passes
            # this handler and refuses the call, like a missing graph.
            bundle = await asyncio.to_thread(
                partial(
                    load_active_bundle,
                    fallback_environments=("sandbox",),
                    bot_id=cohort_bot_id,
                    customer_id=cohort_key,
                    channel="voice",
                )
            )
    except KeyError:
        logger.warning("No active deployment — using minimal fallback instruction")
        bundle = {
            "deploymentId": None,
            "prompt": "You are Priya, an HDFC collections voice agent. Be brief.",
            "persona": {},
            "guardrails": {},
            "voice": {},
            "voiceConfig": {},
            "ttsVoiceId": None,
            "tuning": default_tuning(),
        }

    if sandbox_session and isinstance(sandbox_session.get("persona"), dict):
        bundle = {**bundle, "sandboxPersona": sandbox_session["persona"]}

    bot_id = (
        bundle.get("botId")
        or (bundle.get("promptVersion") or {}).get("botId")
        or _db.DEFAULT_BOT_ID
    )
    # Sandbox Live: reuse the VS- id minted by voice_sandbox.start_voice_sandbox
    # so the session file, voice_sessions row, and CRM interaction join on one key.
    # Non-sandbox transports keep a fresh uuid4 id.
    if sandbox_session and sandbox_session.get("sessionId"):
        session_id = str(sandbox_session["sessionId"])
    else:
        session_id = f"VS-{uuid.uuid4().hex[:10].upper()}"
    transport_name = "asterisk" if call.is_asterisk else ("twilio" if is_twilio else "smallwebrtc")
    session = VoiceSession(
        session_id=session_id,
        deployment_id=bundle.get("deploymentId"),
        transport=transport_name,
    )
    # Twilio CallSid + caller ANI for warm transfer / CRM prefill.
    if call_data is not None:
        session.extra["call_sid"] = getattr(call_data, "call_id", None) or (
            call_data.get("call_id") if isinstance(call_data, dict) else None
        )
        session.extra["from_number"] = getattr(call_data, "from_number", None) or (
            call_data.get("from") if isinstance(call_data, dict) else None
        )
        session.extra["to_number"] = getattr(call_data, "to_number", None) or (
            call_data.get("to") if isinstance(call_data, dict) else None
        )
        body_params = getattr(call_data, "body", None) or {}
        if isinstance(body_params, dict):
            session.extra["twilio_params"] = body_params
            session.extra["call_sid"] = session.extra.get("call_sid") or body_params.get(
                "call_sid"
            )
            session.extra["from_number"] = session.extra.get("from_number") or body_params.get(
                "from"
            )
            session.extra["to_number"] = session.extra.get("to_number") or body_params.get("to")
            # The mission has to be known *here*, not in on_client_connected:
            # the flow graph is compiled further down this function and the
            # objective is what chooses which node the call starts at. Reading
            # it at connect time would mean every outbound mission compiled
            # against the inbound entry and then arrived too late to matter.
            if str(body_params.get("call_type") or "").strip().lower() == "outbound":
                session.extra["attempt_id"] = (
                    str(body_params.get("attempt_id") or "").strip() or None
                )
                session.extra["objective"] = (
                    str(body_params.get("objective") or "").strip() or None
                )
                # Closes the arc: this id was already being written into the
                # stream parameters and read by nothing, so an outcome could
                # never attach to the decision that caused the call.
                session.extra["treatment_decision_id"] = (
                    str(body_params.get("treatment_decision_id") or "").strip() or None
                )
    if is_twilio and session.extra.get("from_number"):
        try:
            ani = session.extra["from_number"]
            if caller_match is not None and ani == pre_from_number:
                matched = caller_match
            else:
                matched = await asyncio.to_thread(_caller_match, ani)
            if matched:
                session.extra["pstn_customer"] = matched
                logger.info(
                    "Twilio caller matched customer=%s dpd=%s",
                    matched.get("customerId"),
                    matched.get("dpd"),
                )
        except Exception:
            logger.exception("Twilio caller lookup failed")
    # A bundle carrying a sandbox persona is a rehearsal: the "caller" is a
    # tester reading a script and no customer is contacted. The contact rules
    # (calling window, DND) must not judge it — flagging a 20:43 rehearsal as an
    # RBI hours breach cost a high-severity self-correction on turn one.
    is_simulated = isinstance(bundle.get("sandboxPersona"), dict)
    # Stream parameters carry call_type, not callDirection. Defaulting the sink
    # to inbound here made outbound live QA skip the RBI hours check.
    call_direction = resolve_call_direction(session, bundle)
    session.extra["call_direction"] = call_direction
    sink = CrmSink(
        session,
        guardrails=bundle.get("guardrails") or {},
        direction=call_direction,
        simulated=is_simulated,
    )
    # "Max call duration" from the Guardrails tab. It was authored, published
    # and read by nobody: every call ran to the fixed platform cap regardless
    # of the slider. It can only ever shorten a call — `_max_duration_watchdog`
    # takes the smaller of the two — so an authored value cannot buy a longer
    # call than the platform allows.
    try:
        _guardrail_secs = int((bundle.get("guardrails") or {}).get("maxSeconds") or 0)
    except (TypeError, ValueError):
        _guardrail_secs = 0
    if _guardrail_secs > 0:
        session.extra["guardrail_max_seconds"] = _guardrail_secs
    # Same tab, same fate: "Max turns" was authored and read by nobody on
    # voice. The count the sink keeps feeds the watchdog in bot_handlers.
    try:
        _guardrail_turns = int((bundle.get("guardrails") or {}).get("maxTurns") or 0)
    except (TypeError, ValueError):
        _guardrail_turns = 0
    if _guardrail_turns > 0:
        session.extra["guardrail_max_turns"] = _guardrail_turns

    system_instruction = _system_instruction_from_bundle(bundle)

    call.sandbox_session = sandbox_session
    call.is_twilio = is_twilio
    call.sandbox_load_error = sandbox_load_error
    call.bundle = bundle
    call.bot_id = bot_id
    call.transport_name = transport_name
    call.session = session
    call.sink = sink
    call.system_instruction = system_instruction


async def load_mission(call) -> None:
    """The outbound mission briefing and its signed Action Contract."""
    session = call.session

    # The mission briefing. Appended to the persona rather than replacing it:
    # who the agent *is* comes from the published card, and why they are on this
    # particular call comes from the decision that placed it. Both are needed and
    # neither is the other.
    #
    # Loaded here because the flow graph is compiled a few lines below and the
    # briefing has to be in the system prompt before the first turn is built. A
    # A non-treatment mission may still degrade to the ordinary script.
    # A treatment mission carries a signed Action Contract and fails before
    # speech if that contract is missing, stale, or tampered.
    _mission: dict[str, Any] | None = None
    if session.extra.get("attempt_id"):
        try:
            import mission as mission_mod

            task = getattr(call, "_mission_io_task", None)
            if task is not None:
                _mission = await task
            else:
                _mission = await asyncio.to_thread(
                    _load_mission_row, str(session.extra["attempt_id"])
                )
        except Exception:
            logger.exception("mission load failed")
        if session.extra.get("treatment_decision_id") and not _mission:
            raise RuntimeError("outbound treatment mission is unavailable")
        if _mission:
            action_contract = _mission.get("actionContract")
            if _mission.get("decisionId"):
                from bank_boundary import snapshots
                from bank_boundary.snapshots import ContractError

                try:
                    if not isinstance(action_contract, dict):
                        raise ContractError("missing")
                    snapshots.validate(action_contract)
                    if action_contract.get("decision_id") != _mission.get("decisionId"):
                        raise ContractError("stale")
                except ContractError as exc:
                    raise RuntimeError(
                        f"outbound action contract refused: {exc}"
                    ) from exc
                session.extra["required_assertions"] = list(
                    action_contract["required_assertions"]
                )
                session.extra["action_contract_validated"] = True
            session.extra["mission"] = _mission
            # The card's entry node wins over the objective lookup when both
            # exist; they agree unless someone edited one of them, and G-OB2
            # blocks publishing that state.
            if _mission.get("entryNode"):
                session.extra["entry_node"] = _mission["entryNode"]
            if _mission.get("allowedOffers") == []:
                # Same latch the hardship interlock uses. A mission with no
                # allowed offers must not be able to reach a product pitch by
                # any route, prompt included.
                session.extra["upsell_blocked"] = "mission_forbids_offers"
            if _mission.get("maxDurationSec"):
                session.extra["max_duration_sec"] = int(_mission["maxDurationSec"])
            if _mission.get("customerName"):
                session.extra["expected_customer_name"] = _mission["customerName"]
            # The briefing is a developer block, not part of the system prefix.
            # Appended to the prefix it made every outbound call's system
            # message unique to the borrower (their name, balance, mission), so
            # the prefix a provider could cache -- and the prefix a regulator
            # reads as "what this deployment says" -- differed per call. It is
            # injected after the persona block below; the direction line
            # ("OUTBOUND CALL -- you placed this call") is the briefing's own.
            try:
                session.extra["mission_briefing"] = mission_mod.briefing(_mission)
            except Exception:
                logger.exception("mission briefing render failed")
        instruction = str(getattr(call, "system_instruction", "") or "")
        if instruction:
            call.system_instruction = _overlay_outbound_persona(instruction)


def _overlay_outbound_persona(instruction: str) -> str:
    """Published cards still say 'inbound' on a dial we placed."""
    return instruction.replace(
        "an inbound collections voice agent",
        "a collections voice agent handling outbound and inbound calls",
    ).replace(
        "inbound collections voice agent",
        "collections voice agent handling outbound and inbound calls",
    )


def build_flow(call) -> None:
    """The mouth grant and the compiled Agent Studio graph."""
    session = call.session
    bundle = call.bundle
    bot_id = call.bot_id
    system_instruction = call.system_instruction
    sandbox_session = call.sandbox_session
    sandbox_persona = call.sandbox_persona
    emitter = call.emitter
    kb_snapshot_id = call.kb_snapshot_id
    kb_enrich = call.kb_enrich
    spoke_probe = call.spoke_probe
    sink = call.sink
    _flow_holder = call._flow_holder
    _start_recording = call._start_recording
    _inject_developer = call._inject_developer
    _replace_developer = call._replace_developer

    from agent_core.skills.runtime import resolve_mouth as _resolve_mouth
    from agent_core.tools.catalog import CATALOG
    from agent_core.tools.schema import CHANNEL_VOICE

    _mouth = _resolve_mouth(
        bundle.get("agentCard") or {},
        frozen_connector_tools=bundle.get("frozenTools"),
    )
    # Not `_tool_state`: build_authored_flow returns its own turn state under
    # that name a few lines below, and they are unrelated types.
    _grant = _mouth.tools(
        channel_tools={spec.name for spec in CATALOG.for_channel(CHANNEL_VOICE)}, channel="voice"
    )
    _allowed_tools = _grant.allowed
    _attached_skills = list(_mouth.packs)
    # Per-member grants off the compiled bundle. Absent (no bundle, or a flat
    # graph) leaves this empty and the single grant above is the whole story —
    # which is every call until a fleet is published.
    _compiled = bundle.get("compiled") if isinstance(bundle, dict) else None
    _specialist_grants: dict[str, set[str]] = {}
    _specialist_entries: dict[str, str] = {}
    if isinstance(_compiled, dict):
        for slug, names in (_compiled.get("grant_by_specialist") or {}).items():
            if isinstance(names, list):
                _specialist_grants[str(slug)] = {str(n) for n in names}
        for slug, key in (_compiled.get("entry_by_specialist") or {}).items():
            if isinstance(key, str) and key:
                _specialist_entries[str(slug)] = key

    # The published Agent Studio graph is the only conversation there is. The
    # Python script this used to fall back to was materialised as
    # agent_core/cards/graphs/collections.json and published like any other
    # graph, so a bot with none refuses the call rather than running
    # something no publish could touch.
    _authored = bundle.get("flow")
    from flow_graph import is_authored

    if is_authored(_authored):
        try:
            from voice.flows_dynamic import build_authored_flow

            _tool_state, _tools, initial_node, global_fns = build_authored_flow(
                session,
                _authored,
                role_message=system_instruction,
                bot_id=bot_id,
                start_recording=_start_recording,
                emitter=emitter,
                kb_snapshot_id=kb_snapshot_id,
                inject_developer=_inject_developer,
                replace_developer=_replace_developer,
                persona=sandbox_persona,
                channel="sandbox_live" if sandbox_session else "voice",
                on_kb_tool_used=kb_enrich.suppress,
                spoke_this_response=lambda: spoke_probe.spoke_this_response,
                sink=sink,
                allowed_tool_names=_allowed_tools,
                attached_skills=_attached_skills,
                agent_card=bundle.get("agentCard") if isinstance(bundle.get("agentCard"), dict) else None,
                objective=session.extra.get("objective") or None,
                entry_node=session.extra.get("entry_node") or None,
                specialist_grants=_specialist_grants,
                specialist_entries=_specialist_entries,
            )
            logger.info(
                "voice flow: using authored graph · mission={}",
                session.extra.get("objective") or "inbound",
            )
        except Exception:
            # The studio is the only source of truth, so a graph that will not
            # compile is a broken deployment, not a call to serve some other
            # way. Falling back is what let a card be edited and published
            # without changing anything the caller heard.
            logger.exception(
                "authored flow failed to compile · bot={} · refusing the call", bot_id
            )
            raise
    else:
        # No published graph at all: a configuration error with a name
        # attached, not something to paper over.
        raise RuntimeError(
            f"bot {bot_id!r} has no published Agent Studio "
            "flow -- publish one (the built-in conversation is "
            "agent_core/cards/graphs/collections.json)"
        )

    _flow_holder["state"] = _tool_state
    # The tool map too: the budget watchdog's hard stop needs `end_call`, and
    # reaching for it through the holder keeps the watchdog from closing over a
    # dict that the authored-graph branch above may have replaced.
    _flow_holder["tools"] = _tools
    expected_name = session.extra.get("expected_customer_name")
    if expected_name and not _tool_state.customer_name:
        _tool_state.customer_name = str(expected_name)

    call._tool_state = _tool_state
    call._tools = _tools
    call.initial_node = initial_node
    call.global_fns = global_fns


def make_flow_manager(call) -> None:
    from pipecat.flows import FlowManager

    transport = call.transport
    llm = call.llm
    context_aggregator = call.context_aggregator
    worker = call.worker
    global_fns = call.global_fns

    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
        global_functions=global_fns,
    )

    call.flow_manager = flow_manager
