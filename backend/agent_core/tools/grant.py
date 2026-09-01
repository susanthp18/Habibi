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
permits, and nothing here lets it: the offer is filtered out of the grant.
Loading a skill is therefore not a permission change — the permission boundary
is pack *attachment*, decided when the card is published.

A cardless mouth is granted nothing (ADR-0002). Callers that still need the
legacy ungated fallback ask :attr:`is_cardless` and supply it themselves, until
the deny-all ticket deletes those branches.

Nothing imports this yet. It is added beside the seven formulas so they can be
migrated one at a time; see the parent issue for the sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Runtime imports stay inside functions: agent_core.cards and
    # agent_core.skills are mutually dependent, and a module-level import here
    # would close the cycle for whichever process touches this first.
    from agent_core.cards.schema import AgentCard
    from agent_core.skills.pack import SkillPack

#: Catalog channel names. Not the card's ``identity.channels`` vocabulary,
#: which spells the text channel "whatsapp" and also carries channels no tool
#: is rendered for.
VOICE = "voice"
TEXT = "text"

#: Zero-argument voice flow control. Deliberately outside the shared tool
#: catalog — a ToolSpec exists to stop argument-name drift *between* channels,
#: and these have no arguments and no second channel. The voice runtime keeps
#: them by unioning a hand-written literal onto whatever set it was handed,
#: which is one of the seven formulas; owning them here is what lets that
#: literal be deleted without silently breaking every call.
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

#: In the catalog and voice-only, but on no card's include list: the built-in
#: flow captures the caller's goal before identity is confirmed, so no author
#: chose it and the grant must supply it.
VOICE_ALWAYS: frozenset[str] = VOICE_FLOW_TOOLS | {"capture_call_goal"}


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

    channel: str
    #: Frozen on purpose. See the module docstring and ADR-0001.
    allowed: frozenset[str]
    card: "AgentCard | None"
    packs: tuple["SkillPack", ...]
    catalog: frozenset[str]

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

        names = offered_tools(
            self.card,
            catalog_names=set(self.catalog),
            attached_skills=list(self.packs) or None,
            active_slug=active_skill,
            channel_tools=_channel_tools(self.channel),
        )
        ordered = [n for n in names if n in self.allowed]
        if self.channel == VOICE:
            # Order is part of what the model sees; the flow tools go last so
            # an authored card's own tools keep the positions they had.
            ordered += sorted(n for n in VOICE_ALWAYS & self.allowed if n not in ordered)
        return tuple(ordered)

    @property
    def is_cardless(self) -> bool:
        """No usable agent card, so no grant exists and nothing is permitted.

        Callers that still fall back to a hardcoded tool list branch on this.
        Those branches are what the deny-all ticket deletes; this module is
        already deny-all and needs no change then.
        """
        return self.card is None

    # -- constructors -------------------------------------------------------

    @classmethod
    def for_bundle(
        cls,
        bundle: Any,
        *,
        channel: str,
        catalog_names: set[str] | None = None,
    ) -> "ToolGrant":
        """The grant for a resolved deployment bundle on one channel.

        ``bundle`` is what ``agent_core.deployment.load_active_bundle`` returns.
        Taking the bundle rather than the card is what makes a handoff cheap:
        the receiving agent's bundle is resolved by bot id and handed straight
        here.
        """
        from agent_core.skills.runtime import resolve_mouth

        raw = bundle.get("agentCard") if isinstance(bundle, dict) else None
        mouth = resolve_mouth(raw or {})
        return cls._build(
            mouth.card, mouth.packs, channel=channel, catalog_names=catalog_names
        )

    @classmethod
    def _build(
        cls,
        card: "AgentCard | None",
        packs: tuple["SkillPack", ...],
        *,
        channel: str,
        catalog_names: set[str] | None = None,
    ) -> "ToolGrant":
        from agent_core.tools.catalog import CATALOG

        catalog = frozenset(catalog_names or set(CATALOG.specs))
        if card is None:
            return cls(
                channel=channel,
                allowed=frozenset(),
                card=None,
                packs=(),
                catalog=catalog,
            )

        from agent_core.skills.intersect import effective_tools

        allowed = set(
            effective_tools(
                card,
                catalog_names=set(catalog),
                attached_skills=list(packs) or None,
                channel_tools=_channel_tools(channel),
            )
        )
        if channel == VOICE:
            allowed |= VOICE_ALWAYS
        return cls(
            channel=channel,
            allowed=frozenset(allowed),
            card=card,
            packs=tuple(packs),
            catalog=catalog,
        )

    @classmethod
    def static_scope(
        cls,
        card: "AgentCard | None",
        packs: tuple["SkillPack", ...] | list["SkillPack"],
        *,
        catalog: set[str] | None = None,
    ) -> frozenset[str]:
        """Everything this card could grant on any channel, for the publish gate.

        Definitionally the union of every reachable dynamic answer, and built
        that way rather than restated — a gate computing its own version is how
        the connector omission happened. A test pins the relationship, so a
        future private formula would have to break it to exist.
        """
        packs = tuple(packs)
        return frozenset().union(
            *(
                cls._build(card, packs, channel=ch, catalog_names=catalog).allowed
                for ch in (VOICE, TEXT)
            )
        )
