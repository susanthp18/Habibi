"""Canonical tool schema layer — one spec, many channel adapters.

Voice (Pipecat Flows) and WhatsApp/text (OpenAI tool dicts) previously each
declared their own JSON schema for the same tool, and the argument names drifted
(``promise_date`` vs ``promisedDate``, ``dispute_type`` vs ``type``,
``scheduled_at`` vs ``scheduledAt``, ``summary`` vs ``transcriptSnippet``).
Two catalogs meant two prompts, two validation rules, and silent breakage when
one side changed.

A :class:`ToolSpec` is now the single source of truth. Each channel renders it:

* ``to_openai_tool()``  → ``bot_runtime`` / sandbox text (OpenAI ``tools=[...]``)
* ``to_flows_schema()`` → Pipecat ``FlowsFunctionSchema`` for the voice FlowManager

Canonical argument names are snake_case. Legacy camelCase names stay live as
:attr:`ArgSpec.aliases` so a model that emits the old name — or a replayed
conversation whose history contains it — still resolves through
:meth:`ToolSpec.normalize_args` instead of raising ``KeyError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable, Iterable, Mapping
from typing import Any

# Channels a spec can be exposed on.
CHANNEL_VOICE = "voice"
CHANNEL_TEXT = "text"  # WhatsApp + sandbox text (both use OpenAI tool dicts)
# Model Context Protocol — an external agent driving these tools. Opt-in per
# spec and never a default: unlike voice and text there is no verification
# ceremony behind it, so exposure is a decision made once per tool in
# catalog.py, not something a new spec inherits by omission.
CHANNEL_MCP = "mcp"


@dataclass(frozen=True)
class ArgSpec:
    """One tool argument, rendered into whichever schema dialect a channel needs."""

    name: str
    type: str
    description: str
    required: bool = False
    enum: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    default: Any = None
    # Legacy / alternate wire names accepted by normalize_args().
    aliases: tuple[str, ...] = ()

    def json_schema(self, *, strict: bool = False) -> dict[str, Any]:
        """JSON Schema for this argument.

        ``strict=True`` renders the shape OpenAI strict function calling
        requires: every property must appear in ``required``, so an optional
        argument is expressed as nullable (``type: [T, "null"]``) instead. The
        model then explicitly emits ``null`` rather than omitting the key, which
        is what made handlers KeyError on a "required" property.
        ``minimum``/``maximum``/``default`` are not supported under strict mode
        and are dropped from the emitted schema (the values stay on the ArgSpec
        for documentation and non-strict channels).
        """
        out: dict[str, Any] = {"type": self.type, "description": self.description}
        if strict and not self.required:
            out["type"] = [self.type, "null"]
        if self.enum:
            enum_values: list[Any] = list(self.enum)
            if strict and not self.required:
                enum_values.append(None)
            out["enum"] = enum_values
        if not strict:
            if self.minimum is not None:
                out["minimum"] = self.minimum
            if self.maximum is not None:
                out["maximum"] = self.maximum
            if self.default is not None:
                out["default"] = self.default
        return out


@dataclass(frozen=True)
class ToolSpec:
    """Channel-agnostic declaration of one agent tool."""

    name: str
    description: str
    args: tuple[ArgSpec, ...] = ()
    channels: frozenset[str] = frozenset({CHANNEL_VOICE, CHANNEL_TEXT})
    # CRM entity this tool creates, for the RTVI `crm.entity` server message.
    entity: str | None = None
    # Habibi route template for deep-links; ``{id}`` is substituted.
    deep_link: str | None = None
    # Voice-only Flows knobs.
    cancel_on_interruption: bool = False
    timeout_secs: float | None = None

    def properties(self, *, strict: bool = False) -> dict[str, Any]:
        return {a.name: a.json_schema(strict=strict) for a in self.args}

    def required_names(self) -> list[str]:
        return [a.name for a in self.args if a.required]

    def to_openai_tool(self, *, strict: bool = True) -> dict[str, Any]:
        """OpenAI ``tools=[...]`` entry for bot_runtime / sandbox text.

        Strict function calling is on by default: the API then guarantees the
        arguments match this schema, which removes a class of runtime failures
        where the model omitted a documented-required property. Strict mode
        requires every property to be listed in ``required`` (optionality is
        carried by the nullable type instead) — ``normalize_args`` already
        tolerates explicit ``None`` values and legacy alias keys, so handlers
        need no change.

        Pass ``strict=False`` for a deployment whose model or API version does
        not support it.
        """
        parameters: dict[str, Any] = {
            "type": "object",
            "properties": self.properties(strict=strict),
            "additionalProperties": False,
        }
        if strict:
            parameters["required"] = [a.name for a in self.args]
        else:
            required = self.required_names()
            if required:
                parameters["required"] = required
        function: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }
        if strict:
            function["strict"] = True
        return {"type": "function", "function": function}

    def to_mcp_tool(self) -> dict[str, Any]:
        """MCP ``tools/list`` entry.

        Non-strict rendering deliberately. MCP has no ``strict`` flag, and the
        strict shape marks every optional argument nullable and lists it as
        required — correct for OpenAI's constrained decoding, actively
        misleading for a human or a general-purpose agent reading the schema to
        decide what to send.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties(strict=False),
                "required": self.required_names(),
                "additionalProperties": False,
            },
        }

    def to_flows_schema(self, handler: Callable) -> Any:
        """Pipecat ``FlowsFunctionSchema`` for the voice FlowManager.

        Imported lazily so text-only processes (bot_worker, API) never pay the
        pipecat import cost just to build OpenAI tool dicts.
        """
        from pipecat.flows import FlowsFunctionSchema

        kwargs: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "properties": self.properties(),
            "required": self.required_names(),
            "handler": handler,
            "cancel_on_interruption": self.cancel_on_interruption,
        }
        if self.timeout_secs is not None:
            kwargs["timeout_secs"] = self.timeout_secs
        return FlowsFunctionSchema(**kwargs)

    def normalize_args(self, raw: Mapping[str, Any] | None) -> dict[str, Any]:
        """Map any accepted wire name onto the canonical snake_case name.

        Canonical keys win over aliases, so a model that sends both
        ``promise_date`` and ``promisedDate`` does not get the alias silently
        overwriting the real value. Unknown keys are dropped — the tool contract
        is the spec, not whatever the model invented.
        """
        src = dict(raw or {})
        out: dict[str, Any] = {}
        for arg in self.args:
            if arg.name in src and src[arg.name] is not None:
                out[arg.name] = src[arg.name]
                continue
            found = False
            for alias in arg.aliases:
                if alias in src and src[alias] is not None:
                    out[arg.name] = src[alias]
                    found = True
                    break
            if not found and arg.default is not None:
                out[arg.name] = arg.default
        return out

    def missing_required(self, normalized: Mapping[str, Any]) -> list[str]:
        return [
            a.name
            for a in self.args
            if a.required and (a.name not in normalized or normalized[a.name] in (None, ""))
        ]

    def link_for(self, entity_id: str | None) -> str | None:
        if not self.deep_link or not entity_id:
            return None
        return self.deep_link.replace("{id}", str(entity_id))


@dataclass
class ToolCatalog:
    """Registry of :class:`ToolSpec` keyed by name."""

    specs: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self.specs:
            raise ValueError(f"duplicate tool spec: {spec.name}")
        self.specs[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self.specs.get(name)

    def for_channel(self, channel: str) -> list[ToolSpec]:
        return [s for s in self.specs.values() if channel in s.channels]

    def openai_tools(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """OpenAI tool dicts, defaulting to every text-channel spec."""
        if names is None:
            chosen = self.for_channel(CHANNEL_TEXT)
        else:
            chosen = [self.specs[n] for n in names if n in self.specs]
        return [s.to_openai_tool() for s in chosen]

    def mcp_tools(self) -> list[dict[str, Any]]:
        """MCP ``tools/list`` payload — every spec that opted into CHANNEL_MCP."""
        return [s.to_mcp_tool() for s in self.for_channel(CHANNEL_MCP)]

    def normalize(self, name: str, raw: Mapping[str, Any] | None) -> dict[str, Any]:
        """Normalize args for ``name``; unknown tools pass through untouched."""
        spec = self.specs.get(name)
        if spec is None:
            return dict(raw or {})
        return spec.normalize_args(raw)
