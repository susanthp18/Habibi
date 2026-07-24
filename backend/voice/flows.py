"""Collections call script as a Pipecat Flows node graph (plan §3.1).

Improvements from flow_improve.md (Pipecat Flows 1.0):
  - Intent-based hub (no menu phrasing); common actions on hub
  - respond_immediately=False where the bot should listen
  - pre_actions tts_say bridges; post_actions end_conversation on terminals
  - Policy/FAQ via global search_knowledge_base (no dedicated Q&A node)
  - global: escalate, KB, notes, pause, end_call

Graph:
  greet+disclose → verify_identity ─┬─(fail ×3 / refuse / 3rd party)→ terminate_politely
                                    └─(ok)→ state_position (hub)
                                              ├─ create_promise_to_pay / request_callback (direct)
                                              ├─ begin_negotiate → negotiate_ptp → gated_upsell → wrap_up
                                              ├─ begin_dispute   → handle_dispute → escalate_close
                                              └─ begin_wrap_up / end_call
  any node (global) → escalate_to_human | search_knowledge_base | add_customer_note
                    | pause_for_caller | end_call
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from voice.rtvi_events import RtviEmitter
from voice.session import VoiceSession
from voice.tools import DeveloperInjector, ToolState, build_tools

AsyncStartRecording = Callable[[], Awaitable[None]]


def build_collections_flow(
    session: VoiceSession,
    *,
    role_message: str,
    bot_id: str | None = None,
    start_recording: AsyncStartRecording | None = None,
    emitter: RtviEmitter | None = None,
    kb_snapshot_id: str | None = None,
    inject_developer: DeveloperInjector | None = None,
    persona: dict[str, Any] | None = None,
    channel: str = "sandbox_live",
    on_kb_tool_used: Callable[[], None] | None = None,
    sink: Any | None = None,
) -> tuple[ToolState, dict[str, Any], Callable[[], dict[str, Any]], list[Any]]:
    """Wire tools + node factories.

    Returns (tool_state, tools_by_name, initial_node_factory, global_functions).
    """

    nodes: dict[str, Callable[[], dict[str, Any]]] = {}
    state, tools = build_tools(
        session,
        bot_id=bot_id,
        start_recording=start_recording,
        nodes=nodes,
        emitter=emitter,
        kb_snapshot_id=kb_snapshot_id,
        inject_developer=inject_developer,
        persona=persona,
        channel=channel,
        on_kb_tool_used=on_kb_tool_used,
        sink=sink,
    )

    # role_message persists across nodes until re-set; re-state on RESET nodes.
    role = role_message

    def greet_disclose() -> dict[str, Any]:
        return {
            "name": "greet_disclose",
            "role_message": role,
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Speak first — one short greeting that also says the call is "
                        "recorded for quality and compliance. Only AFTER that spoken "
                        "sentence, call disclose_recording. Never call a tool before "
                        "speaking. No account details yet. If asked whether you are a "
                        "bot, answer honestly in one short sentence and continue."
                    ),
                }
            ],
            "functions": [tools["disclose_recording"]],
            "respond_immediately": True,
        }

    def verify_identity() -> dict[str, Any]:
        return {
            "name": "verify_identity",
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Speak first: ask only for the last 4 digits of their registered "
                        "mobile. Do NOT call verify_identity until the caller has said "
                        "digits. The value argument must be digits they spoke — never "
                        "placeholder text. Max 3 real attempts. "
                        "If they refuse to verify, call refuse_verification (after 2 "
                        "refusals the call ends). If they say they are not the account "
                        "holder or a third party, call not_account_holder. "
                        "Never state a balance here."
                    ),
                }
            ],
            "functions": [
                tools["verify_identity"],
                tools["refuse_verification"],
                tools["not_account_holder"],
            ],
            # Ask once via LLM, then listen — user may need a moment for digits.
            "respond_immediately": True,
        }

    def state_position() -> dict[str, Any]:
        return {
            "name": "state_position",
            "role_message": role,
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Call get_account_position first. In one short sentence, state "
                        "outstanding and minimum due in INR. If accountTail is missing, "
                        "do not mention account ending at all. "
                        "Then listen to what the caller wants and take the matching "
                        "action — do NOT read them a menu of options. "
                        "Payment / PTP → create_promise_to_pay (or begin_negotiate if "
                        "they need to discuss amounts first). "
                        "Callback later → request_callback. "
                        "Dispute / already paid → begin_dispute. "
                        "Policy / FAQ question → search_knowledge_base (available "
                        "globally; follow answer_policy). "
                        "Wants a statement, no-dues certificate, interest "
                        "certificate, or receipt → request_documents. "
                        "Done / goodbye → begin_wrap_up or end_call. "
                        "If they name two intents, acknowledge both and handle them "
                        "in order. Abuse, legal threats, or lawyer mention → "
                        "escalate_to_human(reason='compliance'). Hardship → "
                        "request_callback(reason='hardship_review') or escalate."
                    ),
                }
            ],
            # ≤5–6 node-local tools (+ globals). Common actions on the hub.
            "functions": [
                tools["get_account_position"],
                tools["create_promise_to_pay"],
                tools["request_callback"],
                tools["begin_negotiate"],
                tools["begin_dispute"],
                tools["begin_wrap_up"],
            ],
            "respond_immediately": True,
        }

    def negotiate_ptp() -> dict[str, Any]:
        return {
            "name": "negotiate_ptp",
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Help the caller commit to a promise-to-pay. Confirm amount "
                        "(must be > 0 and not exceed outstanding by more than 5%) and a "
                        "concrete YYYY-MM-DD date, then call create_promise_to_pay. "
                        "If they prefer a later call, use request_callback. Do not "
                        "invent waivers. Policy questions: search_knowledge_base."
                    ),
                }
            ],
            "functions": [
                tools["get_account_position"],
                tools["create_promise_to_pay"],
                tools["request_callback"],
                tools["begin_wrap_up"],
                tools["return_to_position"],
            ],
            "pre_actions": [
                {
                    "type": "tts_say",
                    "text": "Happy to set that up.",
                    "append_text_to_context": False,
                }
            ],
            "respond_immediately": False,
        }

    def handle_dispute() -> dict[str, Any]:
        return {
            "name": "handle_dispute",
            "role_message": role,
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Capture the dispute carefully. Classify as paid_already, "
                        "wrong_amount, not_my_account, fee_waiver, duplicate_charge, or "
                        "fraud. Call flag_dispute with type, optional amount, and a short "
                        "summary. Do not promise a waiver or resolution."
                    ),
                }
            ],
            "functions": [
                tools["flag_dispute"],
                tools["return_to_position"],
            ],
            # APPEND (default): keep the dispute the caller already stated on the hub.
            # respond_immediately=True: act on that existing statement — False left a
            # dead air gap until the idle ladder (logs: bridge → 6s silence → nudge).
            "pre_actions": [
                {
                    "type": "tts_say",
                    "text": "I understand, let me note that carefully.",
                    "append_text_to_context": False,
                }
            ],
            "respond_immediately": True,
        }

    def gated_upsell() -> dict[str, Any]:
        return {
            "name": "gated_upsell",
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Only if the caller seems receptive and sentiment is not "
                        "negative, briefly mention ONE relevant product and ask "
                        "consent to continue. If they decline or sound frustrated, "
                        "call begin_wrap_up immediately. Do not pressure.\n"
                        "Before pitching, call check_product_eligibility with the "
                        "product id — if it returns eligible=false, do NOT pitch it "
                        "and do not explain why; go to begin_wrap_up.\n"
                        "Only after the caller clearly expresses interest, call "
                        "capture_lead so a specialist can follow up. Never promise "
                        "approval, rates, or limits — capture interest only."
                    ),
                }
            ],
            # Node-scoped tools (Flows best practice): eligibility → capture → exit.
            "functions": [
                tools["check_product_eligibility"],
                tools["capture_lead"],
                tools["begin_wrap_up"],
            ],
            # Topic hop: collapse the collections negotiation into a summary before
            # loading product context, so the upsell turn isn't reasoning over the
            # full PTP haggle. Registered in bot.py via FlowManager.register_action.
            "pre_actions": [
                {"type": "summarize_context"},
                {"type": "mesh_activate_insurance"},
            ],
            "respond_immediately": True,
        }

    def wrap_up() -> dict[str, Any]:
        return {
            "name": "wrap_up",
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "End the call when: a PTP was captured, or a callback was "
                        "booked, or a dispute was logged, and the caller has nothing "
                        "else — or they said goodbye / that's all. "
                        "Summarise what was agreed in one short sentence and thank "
                        "them. Do not ask new questions."
                    ),
                }
            ],
            "functions": [],
            "respond_immediately": True,
            "post_actions": [{"type": "end_conversation"}],
        }

    def terminate_politely() -> dict[str, Any]:
        return {
            "name": "terminate_politely",
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Apologise briefly, explain you cannot share account details "
                        "without verification, and suggest calling from the registered "
                        "number. Do not ask further questions."
                    ),
                }
            ],
            "functions": [],
            "respond_immediately": True,
            "post_actions": [{"type": "end_conversation"}],
        }

    def escalate_close() -> dict[str, Any]:
        return {
            "name": "escalate_close",
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Briefly reassure that a human agent will follow up; avoid "
                        "further negotiation. Do not ask further questions."
                    ),
                }
            ],
            "functions": [],
            "respond_immediately": True,
            "post_actions": [{"type": "end_conversation"}],
        }

    nodes.update(
        {
            "greet_disclose": greet_disclose,
            "verify_identity": verify_identity,
            "state_position": state_position,
            "negotiate_ptp": negotiate_ptp,
            "handle_dispute": handle_dispute,
            "gated_upsell": gated_upsell,
            "wrap_up": wrap_up,
            "terminate_politely": terminate_politely,
            "escalate_close": escalate_close,
        }
    )

    # Global: available on every node (docs: FlowManager global_functions).
    # Document requests are global because callers ask for a statement or NOC at
    # any point in the script, not at one scripted step.
    global_functions = [
        tools["escalate_to_human"],
        tools["search_knowledge_base"],
        tools["get_customer_context"],
        tools["get_payment_history"],
        tools["get_emi_schedule"],
        tools["add_customer_note"],
        tools["request_documents"],
        tools["pause_for_caller"],
        tools["end_call"],
    ]
    return state, tools, greet_disclose, global_functions
