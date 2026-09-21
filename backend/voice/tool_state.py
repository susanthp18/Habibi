"""The trunk of the voice tool set: what every section and build_tools share.

Module-level state and helpers that used to sit at the top of voice/tools.py,
plus ``ToolBuildContext`` -- the closure scope of ``build_tools`` as an object,
so the handler sections can be modules instead of 2,700 lines of nested
functions. ``voice.tools`` re-exports every public name; import from there.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Set as AbstractSet
from typing import Any, Awaitable, Callable

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from agent_core.context import CallContext, account_tail
from agent_core.tools.catalog import (
    VERIFY_METHODS,
)
from agent_core.tools.grant import VOICE_ALWAYS as ALWAYS_ON  # live filter; do not restate
from agent_core.reco import talk as reco_talk
from voice.session import VoiceSession

from types import SimpleNamespace

logger = logging.getLogger(__name__)

# Retain fire-and-forget asyncio tasks so they are not GC'd mid-flight, keyed by
# session. A single module-level set meant every concurrent call shared one
# bucket, so under VOICE_EMBEDDED_HOST=true caller A hanging up cancelled
# caller B's in-flight RTVI emits — B's Inspector silently stopped receiving
# flow.node breadcrumbs mid-call. `None` is the single-session/legacy bucket.
_session_tasks: dict[str | None, set[asyncio.Task[Any]]] = {}
_session_tasks_lock = threading.Lock()

# Reasons that latch the offer engine. Pitching after a medical / income-loss
# declaration is the conduct failure; a later successful PTP may clear this
# latch. ``mission_forbids_offers`` is a different key and must stay.
HARDSHIP_UPSELL_REASONS = frozenset({"income_loss", "medical"})


def spawn_session_task(session_id: str | None, coro: Any) -> asyncio.Task[Any]:
    """Fire-and-forget a coroutine, retained against GC, scoped to one call."""
    task = asyncio.ensure_future(coro)
    with _session_tasks_lock:
        _session_tasks.setdefault(session_id, set()).add(task)

    def _discard(finished: asyncio.Task[Any]) -> None:
        with _session_tasks_lock:
            bucket = _session_tasks.get(session_id)
            if bucket is not None:
                bucket.discard(finished)

    task.add_done_callback(_discard)
    return task


async def drain_background_tasks(session_id: str | None, timeout: float = 2.0) -> None:
    """Settle one call's pending RTVI emits at its teardown.

    Without this, in-flight node-transition emits outlive the pipeline and
    Python logs "Task was destroyed but it is pending!" at interpreter exit.
    Emits are best-effort UI signalling, so a slow data channel is cancelled
    rather than allowed to hold up the hangup path.

    ``session_id`` is required, not defaulted: the bug being fixed here is
    precisely that "no argument" used to mean "cancel everything, including
    other live calls".
    """
    with _session_tasks_lock:
        pending = [t for t in _session_tasks.get(session_id, ()) if not t.done()]
    if not pending:
        return
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            logger.debug("rtvi emit failed: %s", task.exception())


def release_session_tasks(session_id: str | None) -> None:
    """Drop a finished call's bucket so the map does not grow unbounded."""
    with _session_tasks_lock:
        _session_tasks.pop(session_id, None)

NextNodeFactory = Callable[[], dict[str, Any]]
AsyncStartRecording = Callable[[], Awaitable[None]]
# Called with a list of developer messages to append to the LLM context.
DeveloperInjector = Callable[[list[dict[str, str]]], Awaitable[None]]
# Called with (prefix, message) to REPLACE a developer block rather than append.
DeveloperReplacer = Callable[[str, dict[str, str]], Awaitable[None]]

# KB retrieval confidence — below this, refuse to answer from snippets.
KB_CONFIDENCE_THRESHOLD = 0.70

_VERIFY_METHODS = VERIFY_METHODS

def _transfer_mode() -> str:
    """callback_queue (Inbox) unless VOICE_HANDOFF_MODE=warm and PSTN call_sid present.

    Falls back to ``callback_queue`` on any failure — a caller asking for a
    human is the worst possible moment to raise — but says so loudly.
    ``voice_handoff_mode`` deliberately raises on an unrecognised value, its
    docstring reasoning that an operator who typed ``warn`` expecting warm
    transfers "would never find out". A bare ``except Exception: return
    'callback_queue'`` here produced exactly that outcome: the raise was
    swallowed on the one path that consumes it, and the typo stayed invisible.
    """
    try:
        from voice.config import voice_handoff_mode

        return voice_handoff_mode()
    except RuntimeError as exc:
        # Misconfiguration, not a transient fault: worth an ERROR every time it
        # is hit. Escalations are rare enough that this cannot flood a log.
        logger.error("VOICE_HANDOFF_MODE is invalid (%s) — falling back to callback_queue", exc)
        return "callback_queue"
    except Exception:
        logger.exception("handoff mode unreadable — falling back to callback_queue")
        return "callback_queue"


def _account_tail(account_id: str | None) -> str | None:
    """Last 4 DIGITS of an account id — never letters (shared with CallContext)."""
    return account_tail(account_id)


_FAREWELL_TASK = (
    "Briefly thank the caller and say goodbye in one short sentence. "
    "Do not ask further questions."
)

# Matches agent_core.sentiment.sentiment_label's negative boundary, so "too
# negative to ask" means the same thing here as it does everywhere else.
_PROBE_SENTIMENT_FLOOR = -0.15

# The close probe. One question, asked once, never a menu.
#
# W12 removed its `{offer}` injection point rather than leaving it and never
# filling it. §9.7 forbids a promotional utterance inside a recorded
# collections call, and a template with a slot for one is a slot somebody
# fills: an empty string is a policy, an absent placeholder is a property.
# The offer is still scored at the close (see `_prepare_close_probe`); it is
# simply not spoken.
_PRE_CLOSE_TASK = (
    "Ask ONE short question: whether there is anything else you can help them "
    "with today. Do not list options and do not summarise the call again."
    "\n"
    "If they say no or that's all, call end_call. "
    "If they raise a new topic, call return_to_position and handle it. "
    "Never ask this question twice."
)


# Spoken money formatting lives in the shared reco package so voice and chat
# cannot drift into quoting the same offer three ways.
_speakable_inr = reco_talk.speakable_amount


def _end_node(*, farewell_task: str, session: VoiceSession | None = None) -> dict[str, Any]:
    """Terminal node: LLM speaks the farewell, then Flows ends the call.

    Uses built-in ``end_conversation`` post-action (docs: pipecat-flows/guides/actions).
    Post-actions run after TTS finishes — no sleep guessing.
    """
    if session is not None:
        session.mark_ending("bot_farewell")
    return {
        "name": "call_ended",
        "task_messages": [
            {
                "role": "developer",
                "content": farewell_task,
            }
        ],
        "functions": [],
        "respond_immediately": True,
        "post_actions": [{"type": "end_conversation"}],
    }


class ToolState:
    """Mutable per-call state shared by tool closures + flow nodes."""

    def __init__(self) -> None:
        self.verify_attempts = 0
        self.verify_refusals = 0
        self.disclosure_done = False
        # Whether the caller has already been told their outstanding and
        # minimum due on this call. The hub's opening directive and this tool's
        # own "say" hint both instruct the model to state the position, and
        # both are re-read every time the flow re-enters the hub — so a caller
        # who came back to the hub twice heard the same two figures three times
        # (VS-92CDE3F088). Stating a balance is a once-per-call act unless the
        # caller asks again.
        self.position_stated = False
        self.minimum_due: float | None = None
        self.dpd: int | None = None
        self.customer_name: str | None = None
        # Current Flows node — decides which KB corpus a search hits.
        self.current_node: str = "greet_disclose"
        # Live node registry (shared dict, set by build_tools).
        self.nodes: dict[str, Any] = {}
        # Populated at verify; the authoritative CRM snapshot for this call.
        self.call_context: CallContext | None = None
        # One shared read of the 360-degree customer contract per short window,
        # instead of one per tool. See :func:`customer_snapshot`.
        self._customer_row: tuple[str, float, Any] | None = None
        self._customer_lock: asyncio.Lock | None = None
        # Product last discussed on the upsell node, for lead capture defaults.
        self.last_product_id: str | None = None
        self.upsell_presented = False
        # --- one graph advertises both tools ---
        # Under the legacy graph the upsell was reachable ONLY from a successful
        # create_promise_to_pay, so the ordering was enforced by the graph
        # itself. A merged hub advertises both tools at once, and a prompt line
        # alone would leave the bot one hallucinated tool call away from
        # pitching insurance to an angry caller who has agreed to nothing.
        self.commitment_secured = False
        # KB corpus scope. Legacy derives this from current_node
        # (_PRODUCT_NODES = {"gated_upsell"}); with that node gone the hub needs
        # an explicit mode, or product questions get answered from collections
        # docs. Sticky for the rest of the call, matching legacy behaviour
        # (you never leave gated_upsell except to wrap up).
        self.product_scope = "collections"
        #: Namespace -> that member's executable set. Empty on a flat graph.
        self.specialist_grants: dict[str, set[str]] = {}
        #: bot_id -> the namespaced node a hop into that member lands on. Comes
        #: from the same merge that wrote the namespaces, so a hop cannot aim at
        #: a name the graph spells differently.
        self.specialist_entries: dict[str, str] = {}
        # The fleet member currently speaking. `None` on a flat graph, which is
        # every graph until a fleet is authored. It decides two things and only
        # two: which namespace a local node name resolves in, and which entry of
        # `grant_by_specialist` the per-turn tool filter reads.
        self.active_specialist: str | None = None
        # --- offer engine ---------------------------------------------------
        # The recommendation this call is working from. capture_lead reports the
        # outcome against it, which is what turns the decision log into training
        # data instead of a write-only audit trail.
        self.offer_decision_id: str | None = None
        self.offered_product_id: str | None = None
        # Every product the engine has put on the table this call. The sourcing
        # guard checks against this set, so the model cannot pitch or capture an
        # id it invented — a prompt line alone never stopped that.
        self.offered_product_ids: set[str] = set()
        self.offer_declined = False
        self.escalated = False
        self.dispute_opened = False
        self.authority_cap: float | None = None
        # Frozen on purpose: the grant arrives from one owner and a caller that
        # could union onto it is how six competing tool formulas happened.
        self.allowed_tools: AbstractSet[str] | None = None
        self.attached_skills: list[Any] = []
        self.active_skill: str | None = None
        # --- close probe ----------------------------------------------------
        # "Anything else?" is asked exactly once, and the guard is code rather
        # than a prompt line: a model that re-enters the closing node must not
        # be able to ask a second time.
        self.close_probe_done = False

    def may_offer(self, name: str, *, namespace: str | None = None) -> bool:
        """Whether the member owning ``namespace`` may be offered ``name``.

        The one-shot filter in :func:`build_tools` narrows to the union over
        every member; this narrows to the one that is speaking. A flat graph has
        no namespace and no per-member grant, so this is ``True`` and the union
        *is* the grant — today's behaviour, unchanged.

        ``ALWAYS_ON`` is exempt for the same reason it is exempt from the grant:
        a mouth that cannot greet, disclose, verify or hang up is not a safer
        mouth, it is a broken one.
        """
        if name in ALWAYS_ON:
            return True
        grant = self.specialist_grants.get(namespace or "")
        return True if grant is None else name in grant




#: How long one customer read may serve the tools of a turn. Short on purpose:
#: this exists to collapse the three-reads-per-turn fan-out, not to hold a
#: balance across a conversation. Any write tool invalidates it outright.
_SNAPSHOT_TTL_S = 3.0


def invalidate_customer_snapshot(state: "ToolState") -> None:
    """Drop the shared read. Called by every write that changes the customer."""
    state._customer_row = None


async def customer_snapshot(state: "ToolState", customer_id: str) -> Any:
    """``db.get_customer`` once per short window, shared by the turn's tools.

    Each of ``get_customer_context``, ``get_payment_history`` and
    ``get_emi_schedule`` called ``db.get_customer`` in its own thread hop, and
    that call is not a row read: it fans out to consent, ledger, *every* EMI
    installment, 25 interaction contracts, promises, disputes, documents and
    notes, then validates a ``CustomerResponse`` -- holding one of the voice
    container's five pooled connections for the whole fan-out. A normal
    "explain my dues" turn calls two or three of them and paid for the same
    fan-out each time, while the model waited.

    Also more coherent than what it replaces, not less: three staggered reads
    could report three different balances inside one turn. One snapshot cannot.

    Single-flight: concurrent tools in the same turn await one read rather than
    starting three. Never shared across calls -- the state object is per-call --
    and never held long: balances move, so the TTL is seconds and any write
    tool drops it (``invalidate_customer_snapshot``).
    """
    import time as _time

    if state._customer_lock is None:
        state._customer_lock = asyncio.Lock()

    cached = state._customer_row
    now = _time.monotonic()
    if cached is not None and cached[0] == customer_id and (now - cached[1]) < _SNAPSHOT_TTL_S:
        return cached[2]

    async with state._customer_lock:
        # Re-check: the tool that held the lock may have just filled it.
        cached = state._customer_row
        now = _time.monotonic()
        if (
            cached is not None
            and cached[0] == customer_id
            and (now - cached[1]) < _SNAPSHOT_TTL_S
        ):
            return cached[2]

        import db

        customer = await asyncio.to_thread(db.get_customer, customer_id)
        state._customer_row = (customer_id, _time.monotonic(), customer)
        return customer


class ToolBuildContext(SimpleNamespace):
    """The closure scope of ``build_tools``: its parameters, the per-call
    ``ToolState``, and the helpers the preamble defines (``_spec``, ``_node``,
    ``_traced`` ...). Each section's ``build`` unpacks what it reads; a section
    that defines a helper a later section needs attaches it here.
    """

