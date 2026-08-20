"""Collections call script as a Pipecat Flows node graph (plan §3.1).

Improvements from flow_improve.md (Pipecat Flows 1.0):
  - Intent-based hub (no menu phrasing); common actions on hub
  - respond_immediately=False where the bot should listen
  - pre_actions tts_say bridges; post_actions end_conversation on terminals
  - Policy/FAQ via global search_knowledge_base (no dedicated Q&A node)
  - global: escalate, KB, notes, pause, end_call

Graph:
  greet+disclose → discover_intent → verify_identity
                                    ├─(fail ×3 / refuse / 3rd party)→ terminate_politely
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
from voice.tools import (
    _FAREWELL_TASK,
    _PRE_CLOSE_TASK,
    DeveloperInjector,
    DeveloperReplacer,
    ToolState,
    build_tools,
)

AsyncStartRecording = Callable[[], Awaitable[None]]

# Why a turn must not just end: the hub used to state the outstanding balance
# and stop, leaving the caller to work out that it was their move. The idle
# ladder then fired — but the ladder escalates *toward hanging up*, so silence
# after a bare statement read as a call going nowhere rather than a bot waiting.
# The cure is at the language layer: never hand back a turn that has not asked
# for something.
_NO_DEAD_AIR = (
    "Never end your turn on a bare statement of fact. Unless the call is "
    "closing, finish with ONE short, specific question that moves things "
    "forward — about what they just raised, or what they would like to do "
    "next. One question, never a list."
)


def _voice_flow_graph() -> str:
    """``VOICE_FLOW_GRAPH`` — imported lazily so tests can build a flow without
    a fully-configured environment."""
    try:
        from voice.config import voice_flow_graph

        return voice_flow_graph()
    except Exception:
        return "legacy"


#: Money-shaped goals are the ones the outstanding balance actually answers.
#: Everything else — a dispute, a document request, a policy question — is a
#: goal the balance interrupts rather than serves.
#:
#: Module scope so ``voice.flow_export`` can name the same set when it
#: materialises this script as an authored graph, instead of restating it.
MONEY_GOAL_INTENTS: frozenset[str] = frozenset(
    {
        "payment",
        "promise_to_pay",
        "ptp",
        "balance",
        "dues",
        "emi",
        "hardship",
        "settlement",
        "negotiation",
    }
)


def build_collections_flow(
    session: VoiceSession,
    *,
    role_message: str,
    bot_id: str | None = None,
    start_recording: AsyncStartRecording | None = None,
    emitter: RtviEmitter | None = None,
    kb_snapshot_id: str | None = None,
    inject_developer: DeveloperInjector | None = None,
    replace_developer: DeveloperReplacer | None = None,
    persona: dict[str, Any] | None = None,
    channel: str = "sandbox_live",
    on_kb_tool_used: Callable[[], None] | None = None,
    spoke_this_response: Callable[[], bool] | None = None,
    on_upsell_engaged: Callable[[], None] | None = None,
    graph: str | None = None,
    sink: Any | None = None,
    allowed_tool_names: set[str] | None = None,
    attached_skills: list[Any] | None = None,
) -> tuple[ToolState, dict[str, Any], Callable[[], dict[str, Any]], list[Any]]:
    """Wire tools + node factories.

    Returns (tool_state, tools_by_name, initial_node_factory, global_functions).
    """

    # Graph shape. Per-session override first so the Sandbox can A/B without a
    # redeploy — which is what makes "run two calls per graph and compare"
    # practical at all.
    resolved_graph = (
        graph
        or session.extra.get("flowGraph")
        or _voice_flow_graph()
        or "legacy"
    )
    hub = str(resolved_graph).strip().lower() == "hub"

    nodes: dict[str, Callable[[], dict[str, Any]]] = {}
    state, tools = build_tools(
        session,
        bot_id=bot_id,
        start_recording=start_recording,
        nodes=nodes,
        hub_node="collections_hub" if hub else "state_position",
        upsell_node=None if hub else "gated_upsell",
        on_upsell_engaged=on_upsell_engaged,
        emitter=emitter,
        kb_snapshot_id=kb_snapshot_id,
        inject_developer=inject_developer,
        replace_developer=replace_developer,
        persona=persona,
        channel=channel,
        on_kb_tool_used=on_kb_tool_used,
        spoke_this_response=spoke_this_response,
        sink=sink,
        allowed_tool_names=allowed_tool_names,
        attached_skills=attached_skills,
    )

    # role_message persists across nodes until re-set; re-state on RESET nodes.
    role = role_message

    # ---------------------------------------------------------------- goal
    _MONEY_INTENTS = MONEY_GOAL_INTENTS

    def _goal_directive() -> str:
        """Opening directive for the hub, conditioned on why the caller called.

        The graph used to open every post-verification turn with "state
        outstanding and minimum due" regardless of what the caller had asked
        for, so someone calling to dispute a fee was read their balance first.
        With no stated goal the old wording is preserved exactly — an outbound
        call, or a caller who never said why, still gets the position first.
        """
        goal = (session.call_goal or "").strip()
        intent = (session.call_goal_intent or "").strip().lower()
        if state.position_stated:
            # The hub is re-entered — after a negotiation, an upsell, a
            # dispute — and this directive is appended to the context every
            # single time. Unconditional, it reads as "open with the balance"
            # on each return, which is how one caller was read the same
            # outstanding and minimum due three times in four minutes.
            return (
                "You have already told the caller their outstanding and "
                "minimum due on this call. Do NOT state either figure again "
                "unless they ask for it. Pick up from what they just said."
            )
        position_first = (
            "Call get_account_position first. In one short sentence, state "
            "outstanding and minimum due in INR. If accountTail is missing, "
            "do not mention account ending at all."
        )
        if not goal:
            return position_first
        if intent in _MONEY_INTENTS:
            return f"The caller called about: {goal} — a money question. " + position_first
        return (
            f"The caller called about: {goal}. Handle THAT first — it is why "
            "they rang. Do NOT recite the outstanding balance unless they ask "
            "for it, or you need it to answer them. get_account_position is "
            "available the moment it becomes relevant."
        )

    def greet_disclose() -> dict[str, Any]:
        return {
            "name": "greet_disclose",
            "role_message": role,
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "Speak first, in ONE short turn: greet them, say the call is "
                        "recorded for quality and compliance, and ask an open question "
                        "about what they need help with today. Put that spoken "
                        "sentence AND the disclose_recording call in the SAME reply — "
                        "the sentence first, the tool call after it, one reply. Never "
                        "reply with the tool call alone.\n"
                        # "Only AFTER that spoken sentence, call disclose_recording"
                        # read as two turns, and the model obliged: on
                        # VS-6B252E0479 its first reply was 16 completion tokens
                        # of pure tool call with no text, so the greeting needed
                        # a second inference and first audio took 3.66s.

                        # Direction is not modelled anywhere, so any claim about it is
                        # a guess. Left open, the model picked one at random and got it
                        # wrong in both directions across runs — "thanks for calling"
                        # on an outbound dial, "I'm calling from" on an inbound one.
                        "Do NOT say 'thanks for calling' or 'I'm calling from' — you "
                        "do not know who dialled whom. Introduce the bank and the "
                        "department only.\n"
                        "Ask for NO digits and share NO account details yet. Say "
                        "nothing about the caller's mood, name or situation — they "
                        "have not spoken yet, so you know none of it."
                    ),
                }
            ],
            "functions": [tools["disclose_recording"]],
            "respond_immediately": True,
        }

    def discover_intent() -> dict[str, Any]:
        """Listen for why they called — before the verification ceremony.

        This node is the fix for a call that opened greet → "share the last 4
        digits" → outstanding balance, never once asking the caller what they
        wanted. Nothing account-specific is exposed here, so the compliance
        ceremony is unchanged; only its framing moves. Verification becomes "to
        pull that up I'll need to verify you" instead of a checkpoint.

        The globals stay attached, which is the second win: a pure policy
        question ("what does your insurance actually cover?") is answerable
        from the KB without an account, which the old graph made impossible.

        ``respond_immediately=False`` is load-bearing. The greeting already ends
        on "what can I help you with today?" — a human asks both in one breath —
        so speaking on arrival here asked the same question twice in a row,
        which is what the first build of this node actually did. This node's job
        is to *wait*, then classify what comes back.
        """
        return {
            "name": "discover_intent",
            "role_message": role,
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        "You have just asked what they need help with. Listen. Do not "
                        "ask again, do not suggest reasons, do not read a list of "
                        "options, and do not guess why they called.\n"
                        "As soon as they say what they want, call "
                        "capture_call_goal(goal_summary=<their words, one short "
                        "phrase>). Never call it before they have spoken, and never "
                        "with a guess or placeholder.\n"
                        "If they ask a general policy or product question that needs "
                        "no account, answer it from search_knowledge_base first, then "
                        "capture the goal.\n"
                        "If they only greet you back or say nothing useful, ask once "
                        "more in different words. If they immediately ask for their "
                        "balance or to pay, that IS the goal — capture it and move "
                        "on.\n"
                        "Share NO account details here and ask for NO digits yet — "
                        "verification comes next, and it will be framed around what "
                        "they just told you."
                    ),
                }
            ],
            "functions": [tools["capture_call_goal"]],
            "respond_immediately": False,
        }

    def verify_identity() -> dict[str, Any]:
        goal = (session.call_goal or "").strip()
        # Framed around the goal the caller just stated, so verification reads
        # as the means to what they asked for rather than an interrogation.
        framing = (
            (
                f"The caller wants: {goal}. In ONE short sentence tell them you "
                "can help with that and need to verify them first, then ask for "
                "the digits. Do not restate their request at length.\n"
            )
            if goal
            else ""
        )
        return {
            "name": "verify_identity",
            "task_messages": [
                {
                    "role": "developer",
                    "content": framing
                    + (
                        "Speak first: ask only for the last 4 digits of their registered "
                        "mobile. Do NOT call verify_identity until the caller has said "
                        "digits. The value argument must be digits they spoke — never "
                        "placeholder text. When they provide last-4 (or full mobile), "
                        "call verify_identity(method='phone_match', value=<digits>). "
                        "Never call get_customer_context / get_account_position / "
                        "search_knowledge_base before verification succeeds. "
                        "Dues / EMI / outstanding / next installment are CRM facts — "
                        "verify first, then the hub will load the account. "
                        "Max 3 real attempts. "
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
                        _goal_directive() + " "
                        "Then listen to what the caller wants and take the matching "
                        "action. Do not recite a menu of options unprompted — but if "
                        "they ASK what you can do, answer with the short capability "
                        "list in one sentence and do not call any tool for it. "
                        "Payment / PTP → create_promise_to_pay (or begin_negotiate if "
                        "they need to discuss amounts first). "
                        "Callback later → request_callback. "
                        "Dispute / already paid → begin_dispute. "
                        "Dues / EMI / balance / next installment → get_account_position "
                        "only — NEVER search_knowledge_base for money facts. "
                        "Policy / insurance FAQ / exclusions → search_knowledge_base "
                        "(available globally; follow answer_policy). "
                        "Wants a statement, no-dues certificate, interest "
                        "certificate, or receipt → request_documents. "
                        "Done / goodbye → begin_wrap_up or end_call. "
                        "If they name two intents, acknowledge both and handle them "
                        "in order. Abuse, legal threats, or lawyer mention → "
                        "escalate_to_human(reason='compliance'). Hardship → "
                        "request_callback(reason='hardship_review') or escalate. "
                        + _NO_DEAD_AIR
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

    def collections_hub() -> dict[str, Any]:
        """state_position + negotiate_ptp + gated_upsell + wrap_up, merged.

        The point is flexibility, not node-count golf: the model can state the
        position, negotiate an amount, offer a product and close — in any order,
        revisiting any of them — without a transition. Node transitions cost a
        function call plus a second inference each, so fewer of them is faster
        too, but that is the by-product.

        Two things the merge cannot express in prose and that live in code
        instead (see voice/tools.py):
          * the upsell ordering guard — ``state.commitment_secured``;
          * the KB corpus switch — ``state.product_scope``, which used to be
            derived from the (now absent) gated_upsell node name.

        gated_upsell's ``summarize_context`` pre-action is deliberately dropped:
        there is no topic *hop* any more, auto-summarisation already covers
        context growth, and firing LLMSummarizeContextFrame from inside a tool
        handler is precisely the mechanism of the VS-0D653BF9C3 incident
        documented in voice/bot.py. Reversible with VOICE_FLOW_GRAPH=legacy.
        """
        return {
            "name": "collections_hub",
            "role_message": role,
            "task_messages": [
                {
                    "role": "developer",
                    "content": (
                        # (1) position — goal-conditioned, was unconditional
                        _goal_directive() + "\n"
                        # (2) no mode changes
                        "You can do everything here — state the position, "
                        "negotiate, take a payment promise, book a callback, "
                        "raise documents, and close the call. Do NOT announce "
                        "steps and do not recite a menu of options unprompted. "
                        "Listen to what the caller wants and take the matching "
                        "action. If they ASK what you can do, answer with the "
                        "short capability list in one sentence, without calling "
                        "any tool.\n"
                        # (3) intent routing, minus the deleted hops
                        "Payment / promise to pay → create_promise_to_pay. "
                        "Callback later → request_callback. "
                        "Dispute or 'already paid' → begin_dispute. "
                        "Fee waiver, bounce reversal, settlement or restructuring → "
                        "begin_dispute. Do not quote a rupee figure until "
                        "evaluate_authority returns one. "
                        "Statement, no-dues certificate, interest certificate or "
                        "receipt → request_documents. "
                        "If they name two intents, acknowledge both and handle "
                        "them in order. Abuse, legal threats, or lawyer mention → "
                        "escalate_to_human(reason='compliance'). Hardship → "
                        "request_callback(reason='hardship_review') or escalate.\n"
                        # (4) money-facts precedence — verbatim from state_position
                        "Dues / EMI / balance / next installment → "
                        "get_account_position ONLY — NEVER search_knowledge_base "
                        "for money facts. Policy / insurance FAQ / exclusions → "
                        "search_knowledge_base (available globally; follow "
                        "answer_policy).\n"
                        # (5) PTP mechanics — from negotiate_ptp
                        "For a promise to pay: confirm an amount greater than 0 "
                        "that does not exceed the outstanding by more than 5%, and "
                        "a specific calendar date, then call "
                        "create_promise_to_pay. Ask for the date the way a person "
                        "would and convert it to YYYY-MM-DD yourself for the tool "
                        "argument — never say a date format out loud. "
                        "Speak the amount, date, and the "
                        "channel last-4 the written confirm went to. Never read a "
                        "payment URL aloud and never invent a link. If they prefer "
                        "a later call, use request_callback. Do not invent waivers.\n"
                        # (6) upsell gating — the engine chooses, not the model
                        "NEVER name a product you were not given by "
                        "recommend_next_offer. Do not guess product ids. If the "
                        "caller asks about products, or once a payment promise or "
                        "callback has been recorded and they seem receptive, call "
                        "recommend_next_offer — it applies every eligibility, "
                        "consent and timing rule for you. If it returns "
                        "suppressed=true or no offers, say nothing about products "
                        "at all and do not explain why. Otherwise mention ONE "
                        "offer in a single short sentence and ask if they would "
                        "like a specialist to explain it. On clear interest call "
                        "capture_lead with the offerId; on refusal call "
                        "decline_offer and move on. Never promise approval, rates "
                        "or limits.\n"
                        # (7) wrap-up — from wrap_up, now one fewer hop
                        "Close the call when a commitment is recorded and they "
                        "have nothing else, or they say goodbye: summarise what "
                        "was agreed in one short sentence, thank them, ask no new "
                        "questions, then call end_call.\n"
                        # (8) the turn must go somewhere
                        + _NO_DEAD_AIR
                    ),
                }
            ],
            # Six node-local tools plus the nine globals. Above the "≤5-6"
            # heuristic once globals are counted — accepted consciously, with
            # the precedence rules above doing the work the graph used to.
            "functions": [
                tools["get_account_position"],
                tools["create_promise_to_pay"],
                tools["request_callback"],
                tools["recommend_next_offer"],
                tools["capture_lead"],
                tools["decline_offer"],
                tools["begin_dispute"],
            ],
            "respond_immediately": True,
        }

    def call_ended() -> dict[str, Any]:
        """Terminal node for end_call.

        Registered (rather than built inline by the tool) so state.current_node
        and the RTVI flow.node stream both see the final hop — and so the call's
        disposition is derivable at teardown.
        """
        return _FAREWELL_NODE()

    def _FAREWELL_NODE() -> dict[str, Any]:
        return {
            "name": "call_ended",
            "task_messages": [{"role": "developer", "content": _FAREWELL_TASK}],
            "functions": [],
            "respond_immediately": True,
            "post_actions": [{"type": "end_conversation"}],
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
                        "specific calendar date, then call create_promise_to_pay. "
                        "ASK for the date the way a person would — \"which day this "
                        "week?\" — and convert it to YYYY-MM-DD yourself when you "
                        "fill in the tool argument. Never say a date format aloud: "
                        "one call asked the caller for \"the exact date in "
                        "YYYY-MM-DD\" and the letters were read out one by one. "
                        "After it returns, confirm the amount, date, and the channel "
                        "the link was sent to (WhatsApp or SMS last-4). Never read a "
                        "payment URL aloud and never invent a link. "
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
                        "fraud. For a fee_waiver, call evaluate_authority first and do "
                        "not quote any rupee figure it did not return. Otherwise call "
                        "flag_dispute with type, optional amount, and a short summary. "
                        "Do not promise a waiver or resolution the matrix did not approve."
                    ),
                }
            ],
            "functions": [
                tools["flag_dispute"],
                tools["evaluate_authority"],
                tools["apply_goodwill"],
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
                        "Call recommend_next_offer first — it chooses the product "
                        "and applies every eligibility, consent, timing and "
                        "frequency rule. NEVER name a product it did not return, "
                        "and never guess a product id.\n"
                        "If it returns suppressed=true or no offers, say nothing "
                        "about products, do not explain why, and call "
                        "begin_wrap_up.\n"
                        "Otherwise mention ONE offer in a single short sentence "
                        "with its indicative amount and ask if they would like a "
                        "specialist to explain it. Do not pressure.\n"
                        "On clear interest call capture_lead with the offerId. If "
                        "they decline or sound frustrated, call decline_offer then "
                        "begin_wrap_up. Never promise approval, rates, or limits — "
                        "capture interest only.\n"
                        "The caller may raise something that is not about the offer "
                        "— a product or policy question, a new request, anything at "
                        "all. Answer THAT instead: use search_knowledge_base for "
                        "product and policy questions and say what it returns. Do "
                        "not qualify them for a lead they did not ask for, and do "
                        "not offer to transfer them unless they ask. When the new "
                        "topic needs the account again, call return_to_position; "
                        "when they are done, call begin_wrap_up so the call closes "
                        "properly."
                    ),
                }
            ],
            # Node-scoped tools: recommend -> capture/decline -> exit, plus a way
            # back to the hub.
            #
            # `return_to_position` is here because without it this node was a
            # trap. On call VS-9BC3DD9725 the caller asked about travel insurance
            # benefits while parked here; the node's only script was the offer
            # ladder, so the bot spent three and a half minutes qualifying a lead
            # nobody asked for — country, dates, duration, personal or family —
            # never called the knowledge base that had the answer, and never
            # reached pre_close, so the call had no ending. The caller hung up on
            # a question.
            "functions": [
                tools["recommend_next_offer"],
                tools["capture_lead"],
                tools["decline_offer"],
                tools["return_to_position"],
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

    def pre_close() -> dict[str, Any]:
        """The "anything else?" turn — the one node with no end_conversation.

        It has to be its own node. The terminals carry
        ``post_actions: end_conversation``, which fires as soon as TTS finishes,
        so a question asked there would hang up on the caller mid-answer. Here
        the bot asks, then waits, and only ``end_call`` closes the line.

        The offer clause is injected at build time from ToolState — empty on
        most calls, populated only when the engine returned something that
        cleared every gate.
        """
        return {
            "name": "pre_close",
            "task_messages": [
                {
                    "role": "developer",
                    "content": _PRE_CLOSE_TASK.format(
                        offer=state.close_probe_offer_clause or ""
                    ),
                }
            ],
            "functions": [
                tools["capture_lead"],
                tools["decline_offer"],
                tools["return_to_position"],
                tools["end_call"],
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

    # Shared by both graphs: entry, verification, the dispute state (a
    # compliance state whose pre_action bridge is load-bearing), and the
    # terminals. call_ended is registered in both so end_call always routes
    # through the registry.
    nodes.update(
        {
            "greet_disclose": greet_disclose,
            "discover_intent": discover_intent,
            "verify_identity": verify_identity,
            "handle_dispute": handle_dispute,
            # Registered in BOTH graphs: end_call is the single chokepoint every
            # clean ending goes through, so the probe must exist on both.
            "pre_close": pre_close,
            "terminate_politely": terminate_politely,
            "escalate_close": escalate_close,
            "call_ended": call_ended,
        }
    )
    if hub:
        nodes["collections_hub"] = collections_hub
    else:
        nodes.update(
            {
                "state_position": state_position,
                "negotiate_ptp": negotiate_ptp,
                "gated_upsell": gated_upsell,
                "wrap_up": wrap_up,
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
