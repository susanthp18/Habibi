"""The Tool Grant — everything one mouth may execute, and what it is offered.

Seven formulas across eight call sites answered some version of "which tools
may this agent call right now", in four modules, and they had already drifted:
the publish gate's copy omits connectors, so a skill pack legitimately naming an
``ext.*`` tool fails a gate the runtime would have passed. This module is the
one owner, and per ADR-0001 it is the *enforcement point* rather than a helper
returning a set — a caller holding a set is free to union onto it, and several
did.

Two properties, both from ADR-0001:

**The grant is derived from the agent card, not from the turn or the session.**
Nothing within a turn can change it, so recomputing per turn is waste. Keying it
to the session is what breaks the moment a handoff is real: the receiving agent
brings its own card and must bring its own grant. Building one is
``for_bundle(bundle, channel=...)``, so doing it twice in a call costs a second
call and nothing else.

**An offer is only ever a subset of the grant.** :meth:`offer` narrows what the
model is shown, for prompt cost. It cannot widen what :meth:`may_execute`
permits, and nothing here lets it: the offer is filtered through the grant.
Loading a skill is therefore not a permission change — the permission boundary
is pack *attachment*, decided when the card is published.

A cardless mouth is granted nothing (ADR-0002).

``voice.tools`` imports :data:`VOICE_ALWAYS` as ``ALWAYS_ON``. The remaining
formulas still compute the grant themselves; they migrate one at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Runtime imports stay inside functions: agent_core.cards and
    # agent_core.skills are mutually dependent, and a module-level import here
    # would close the cycle for whichever process touches this first.
    from agent_core.cards.schema import AgentCard
    from agent_core.skills.pack import SkillPack

#: Catalog channel names. Not the card's ``identity.channels`` vocabulary, which
#: spells the text channel "whatsapp" and carries channels no tool renders for.
VOICE = "voice"
TEXT = "text"

#: Two values, so it is a type rather than a bare string a caller can misspell.
Channel = Literal["voice", "text"]

#: Zero-argument voice flow control. Deliberately outside the shared tool
#: catalog — a ToolSpec exists to stop argument-name drift *between* channels,
#: and these have no arguments and no second channel.
VOICE_FLOW_TOOLS: frozenset[str] = frozenset(
    {
        "disclose_recording",
        "refuse_verification",
        "not_account_holder",
        "begin_negotiate",
        "begin_dispute",
        "begin_wrap_up",
        "return_to_position",
        "pause_for_caller",
        "end_call",
    }
)

#: The full floor the voice runtime keeps regardless of what a card granted.
#:
#: Two catalog tools join the nine above. ``capture_call_goal`` is voice-only and
#: on no card's include list — the built-in flow captures the caller's goal
#: before identity is confirmed, so no author chose it. ``verify_identity`` is
#: here because a call that cannot verify anybody is not a narrower call: every
#: write sits behind ``identity_verified``, and the two verification nodes have
#: no other exit, so a card whose grant omitted it published cleanly and
#: produced a call that verified nobody on the regulated channel.
#:
#: ``voice.tools.ALWAYS_ON`` is this object — imported, not restated. The alias
#: cannot run the other way: this module is what the publish compiler (and
#: therefore :meth:`static_grant`) reads, and ``voice.tools`` is a runtime
#: module full of session-bound closures. ``flow_graph._FLOW_CONTROL_TOOLS``
#: remains a third statement, of editor descriptions rather than the runtime
#: floor. The pin in ``tests/test_tool_grant.py`` reads ``voice/tools.py`` as
#: text rather than importing it, which keeps it cheap in every image.
VOICE_ALWAYS: frozenset[str] = VOICE_FLOW_TOOLS | {"capture_call_goal", "verify_identity"}

#: The text channel's floor. One name, for the same reason ``verify_identity``
#: is in the voice floor: a conversation that cannot work out who it is talking
#: to is not a narrower conversation, it is one where every write is refused.
#:
#: ``bot_runtime`` has told the model on *every* WhatsApp turn to "call
#: identify_customer with phone digits or account last-4 before money or lead
#: tools" since the text path was written. ``identify_customer`` is one of the
#: catalog's two TEXT_ONLY specs, it is on no first-party card's include list
#: and in no skill pack's ``allowed-tools``, and there was no text analogue of
#: this floor — so the name was never in ``tool_state.allowed``, never rendered
#: into the tool list, and ``execute_tool`` refused it as
#: ``tool_not_on_card_or_skill``. The prompt has been assuming this floor
#: exists. Now it does.
#:
#: The catalog's other TEXT_ONLY spec, ``ingest_customer_document``, stays a
#: card grant rather than a floor: uploading a borrower's document is a
#: deliberate capability, not the price of holding a conversation.
TEXT_ALWAYS: frozenset[str] = frozenset({"identify_customer"})


def _channel_tools(channel: str) -> set[str]:
    """Catalog names renderable on this channel.

    The catalog already knows this and is simply not asked on the text path:
    its tool renderer applies the channel filter only when given no explicit
    name list, and the text runtime always gives it one built from the whole
    catalog. So a card naming a voice-only tool renders it into the WhatsApp
    tool list, where no handler exists.
    """
    from agent_core.tools.catalog import CATALOG

    return {spec.name for spec in CATALOG.for_channel(channel)}


@dataclass(frozen=True)
class ToolGrant:
    """What one mouth may execute on one channel, and what to offer it."""

    channel: Channel
    #: Frozen, and read rather than passed around: :meth:`may_execute` is the
    #: enforcement point, so a caller copying this set cannot widen what the
    #: runtime permits. Exposed because the publish gate compares grants and
    #: because a characterization test has to see one.
    allowed: frozenset[str]
    card: "AgentCard | None"
    packs: tuple["SkillPack", ...]
    catalog: frozenset[str]
    frozen_connector_tools: tuple[str, ...] | None = None
    #: The names this channel can render and the always-on set that joined the
    #: grant. Defaulted from ``channel``; a caller with a narrower renderable
    #: set (the text mouth's catalog slice) states it, and the floor is
    #: intersected with it so a mis-stated floor cannot smuggle a voice-only
    #: tool onto text.
    channel_tools: frozenset[str] | None = None
    floor: frozenset[str] = frozenset()

    # -- the interface ------------------------------------------------------

    def may_execute(self, name: str) -> bool:
        """Whether this mouth may run ``name`` at all. The enforcement point."""
        return name in self.allowed

    def offer(self, *, active_skill: str | None = None) -> tuple[str, ...]:
        """What to put in front of the model, in the order it should see them.

        Always a subset of :attr:`allowed`. Skill-gated writes appear only once
        ``active_skill`` names an attached pack that lists them — a prompt-cost
        decision, never a permission one.
        """
        if self.card is None:
            return ()

        from agent_core.skills.intersect import offered_tools

        names = offered_tools(self.card, active_slug=active_skill, **self._inputs())
        ordered = [n for n in names if n in self.allowed]
        # Order is part of what the model sees; the floor goes last so an
        # authored card's own tools keep the positions they had. The floor is in
        # `allowed` by construction, so this only ever appends.
        ordered += sorted(self.floor - set(ordered))
        return tuple(ordered)

    @property
    def is_cardless(self) -> bool:
        """No usable agent card, so no grant exists and nothing is permitted."""
        return self.card is None

    def _inputs(self) -> dict[str, Any]:
        """The arguments both tool computations take. Stated once so the grant
        and the offer cannot be computed against different inputs."""
        return {
            "catalog_names": set(self.catalog),
            "attached_skills": list(self.packs) or None,
            "channel_tools": (
                set(self.channel_tools) if self.channel_tools is not None else _channel_tools(self.channel)
            ),
            # Connectors have a text renderer only. An explicit empty tuple on
            # voice prevents effective_tools from consulting the live registry
            # and silently granting an ext.* name no voice handler can run.
            "frozen_connector_tools": (
                self.frozen_connector_tools if self.channel == TEXT else ()
            ),
        }

    # -- constructors -------------------------------------------------------

    @classmethod
    def for_bundle(cls, bundle: Any, *, channel: Channel) -> "ToolGrant":
        """The grant for a resolved deployment bundle on one channel.

        ``bundle`` is what ``agent_core.deployment.load_active_bundle`` returns.
        Taking the bundle rather than the card is what makes a handoff cheap:
        the receiving agent's bundle is resolved by bot id and handed straight
        here.
        """
        from agent_core.skills.runtime import resolve_mouth

        raw = bundle.get("agentCard") if isinstance(bundle, dict) else None
        mouth = resolve_mouth(raw or {})
        frozen: list[str] | None = None
        compiled = bundle.get("compiled") if isinstance(bundle, dict) else None
        if isinstance(compiled, dict):
            frozen = [
                str(name)
                for connector in compiled.get("connectors") or []
                if isinstance(connector, dict)
                for name in connector.get("tool_names") or []
            ]
        elif isinstance(bundle, dict) and isinstance(bundle.get("frozenTools"), list):
            frozen = [str(name) for name in bundle["frozenTools"]]
        return cls.for_card(
            mouth.card,
            mouth.packs,
            channel=channel,
            frozen_connector_tools=frozen,
        )

    @classmethod
    def for_card(
        cls,
        card: "AgentCard | None",
        packs: tuple["SkillPack", ...] | list["SkillPack"],
        *,
        channel: Channel,
        catalog: set[str] | None = None,
        frozen_connector_tools: list[str] | tuple[str, ...] | None = None,
        channel_tools: set[str] | frozenset[str] | None = None,
        floor: frozenset[str] | None = None,
    ) -> "ToolGrant":
        """The grant for an already-resolved card and its packs.

        Public because it is the real constructor: :meth:`for_bundle` is an
        adapter over it, :meth:`static_grant` unions two of them, the publish
        gate has a card in hand without a deployment bundle to resolve, and
        :meth:`MouthTurn.tools` -- every runtime's turn -- is a thin reading
        of it. There is one formula.

        ``floor`` defaults to the channel's always-on set; ``channel_tools``
        to what the catalog renders on the channel. Both are intersected: a
        floor name the channel cannot render is not granted.
        """
        from agent_core.tools.catalog import CATALOG

        names = frozenset(catalog or set(CATALOG.specs))
        packs = tuple(packs)
        frozen = tuple(frozen_connector_tools) if frozen_connector_tools is not None else None
        renderable = frozenset(channel_tools) if channel_tools is not None else None
        if card is None:
            return cls(
                channel=channel,
                allowed=frozenset(),
                card=None,
                packs=(),
                catalog=names,
                frozen_connector_tools=frozen,
                channel_tools=renderable,
            )

        from agent_core.skills.intersect import effective_tools

        default_floor = VOICE_ALWAYS if channel == VOICE else TEXT_ALWAYS
        base = frozenset(floor if floor is not None else default_floor)
        # Intersected with the caller's renderable set when one is given (the
        # text mouth's catalog slice). The channel default is not intersected:
        # the voice floor names the flow tools, which are no catalog entry and
        # are rendered by the FlowManager, not the catalog.
        if renderable is not None:
            base &= renderable
        grant = cls(
            channel=channel,
            allowed=frozenset(),
            card=card,
            packs=packs,
            catalog=names,
            frozen_connector_tools=frozen,
            channel_tools=renderable,
            floor=base,
        )
        allowed = set(effective_tools(card, **grant._inputs()))
        # A connector tool is offered only through a pack that names it, so
        # the grant holds only those: an `ext.*` name in the grant and in no
        # offer could still execute on a name the model was never shown.
        pack_ext = {n for p in packs for n in p.allowed_tools if n.startswith("ext.")}
        allowed = {n for n in allowed if not n.startswith("ext.") or n in pack_ext}
        return cls(
            channel=channel,
            allowed=frozenset(allowed | base),
            card=card,
            packs=packs,
            catalog=names,
            frozen_connector_tools=frozen,
            channel_tools=renderable,
            floor=base,
        )

    @classmethod
    def static_grant(
        cls,
        card: "AgentCard | None",
        packs: tuple["SkillPack", ...] | list["SkillPack"],
        catalog: set[str] | None = None,
    ) -> frozenset[str]:
        """Everything this card could grant on any channel, for the publish gate.

        Definitionally the union of every reachable dynamic answer, and built
        that way rather than restated — a gate computing its own version is how
        the connector omission happened. ``tests/test_tool_grant.py`` pins the
        relationship permanently, as ADR-0001 requires, so a future private
        formula would have to break that test to exist.

        Named ``static_grant`` and not ``static_scope``: CONTEXT.md lists
        *scope* under what to avoid for a Tool Grant.
        """
        packs = tuple(packs)
        return frozenset().union(
            *(
                cls.for_card(card, packs, channel=ch, catalog=catalog).allowed
                for ch in (VOICE, TEXT)
            )
        )
