"""Persisted compiled-contract shape. One member, one artefact.

The live grant still owns traffic while ``FLEET_ENABLED`` is off. This
document is what publish stores, what the sandbox rehearses against, and
what the Effective-contract inspector reads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PinnedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    version: str
    pin: str = "exact"
    content_hash: str = ""
    signed: bool = False
    mouth: list[str] = Field(default_factory=list)


class FrozenConnector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str
    allow_prefixes: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    digest: str = ""
    #: MCP connectors have no voice renderer. The grant may still list the
    #: ``ext.*`` names (parity with today); the runtime refuses them on voice
    #: with this reason rather than dispatching into a missing handler.
    voice_supported: bool = False


class ChannelGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["voice", "text"]
    allowed: list[str] = Field(default_factory=list)
    offered: list[str] = Field(default_factory=list)


class NodeOffer(BaseModel):
    """One step of the authored graph, against the grant.

    The grant above answers "what may this card call". This answers "what may
    this card call *here*", which is the question every graph-shaped gate asks:
    identity-before-writes walks paths looking for a step that offers a write, a
    door is a card whose every step offers only reads, and the prefix budget is
    a sum over what a step puts in front of the model.

    ``dropped`` is not a hypothetical. A node may name any tool in the catalog —
    the picker, ``/flow/validate`` and G1 all allow it — and the runtime then
    filters the registry to the grant and skips the rest with a log line. So a
    step could offer a way out that the call would never be given. Recording it
    on the artefact is what lets the canvas, the compiler and the runtime give
    one answer.
    """

    model_config = ConfigDict(extra="forbid")

    #: Node key, or the literal ``globalTools`` for the graph-level list.
    key: str
    offered: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)


class CompiledHashes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    persona: str
    guardrails: str
    flow: str
    card: str


class CompiledBundle(BaseModel):
    """One-member compiled contract. ``bundle_hash`` covers every other field."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    bot_id: str
    prompt_version_id: str | None = None
    source_ids: dict[str, str] = Field(default_factory=dict)
    skills: list[PinnedSkill] = Field(default_factory=list)
    connectors: list[FrozenConnector] = Field(default_factory=list)
    grants: list[ChannelGrant] = Field(default_factory=list)
    #: Per-step offers, in graph order. Empty for a card with no authored flow.
    node_offers: list[NodeOffer] = Field(default_factory=list)
    #: Namespace -> the tool names that member may execute. Empty for a flat
    #: graph, which is every graph until a fleet is authored — so the runtime
    #: falls through to :meth:`grant_for` and today's behaviour is unchanged.
    #: This is the thing a hop swaps: without it the receiving specialist would
    #: speak with the sending one's grant, which is precisely what a handoff is
    #: supposed to stop.
    grant_by_specialist: dict[str, list[str]] = Field(default_factory=dict)
    human_gates: list[dict[str, Any]] = Field(default_factory=list)
    hashes: CompiledHashes
    gates: list[dict[str, Any]] = Field(default_factory=list)
    prompt: str = ""
    persona: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, Any] = Field(default_factory=dict)
    #: The card's own authored graph, exactly as published. ``hashes.flow`` is
    #: its digest, which is why the merged graph below is a separate field: a
    #: fleet publish must not make ``parity_report`` disagree with the canvas.
    flow: dict[str, Any] = Field(default_factory=dict)
    #: Every member's graph merged into one, node keys namespaced by bot id.
    #: Empty for a one-member fleet, which is every card today — the runtime
    #: then falls back to ``flow`` and behaviour is unchanged.
    fleet_flow: dict[str, Any] = Field(default_factory=dict)
    #: bot_id -> the namespaced node a hop into that member lands on. Built by
    #: the same merge that wrote the namespaces, so the two cannot disagree
    #: about what a member's entry is called.
    entry_by_specialist: dict[str, str] = Field(default_factory=dict)
    #: bot_id -> the published prompt_version the member's subgraph and grant
    #: were read from. A door's bundle is *derived* from its members' published
    #: versions; naming them here makes the derivation part of the hash, so a
    #: member republish changes the door's bundle_hash and "which version said
    #: this on the hop" resolves from the artefact alone.
    member_versions: dict[str, str] = Field(default_factory=dict)
    agent_card: dict[str, Any] = Field(default_factory=dict)
    bundle_hash: str = ""

    def grant_for(self, channel: str) -> ChannelGrant | None:
        return next((g for g in self.grants if g.channel == channel), None)

    def allowed_for(self, channel: str, specialist: str | None = None) -> frozenset[str]:
        """What ``specialist`` may execute on ``channel``.

        Falls back to the channel grant when the graph is flat or the namespace
        is unknown — an unrecognised specialist must not silently mean "no
        tools", which would strand a live call mid-sentence. A namespace that
        should not have been reachable is a compile-time error (G-F4), caught
        before the call, not a mid-call amputation.
        """
        if specialist and specialist in self.grant_by_specialist:
            return frozenset(self.grant_by_specialist[specialist])
        grant = self.grant_for(channel)
        return frozenset(grant.allowed if grant else ())
