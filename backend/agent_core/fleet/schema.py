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
    human_gates: list[dict[str, Any]] = Field(default_factory=list)
    hashes: CompiledHashes
    gates: list[dict[str, Any]] = Field(default_factory=list)
    prompt: str = ""
    persona: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, Any] = Field(default_factory=dict)
    flow: dict[str, Any] = Field(default_factory=dict)
    agent_card: dict[str, Any] = Field(default_factory=dict)
    bundle_hash: str = ""

    def grant_for(self, channel: str) -> ChannelGrant | None:
        return next((g for g in self.grants if g.channel == channel), None)
