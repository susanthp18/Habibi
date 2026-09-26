"""Canonical snapshots and live-tool policy checks shared by REST and MCP."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator
from jsonschema import Draft202012Validator


def snapshot_tool(tool: Any) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "definition": tool.definition,
    }


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def mcp_schema_digest(name: str, properties: dict, required: list,
                      *, full_schema: dict | None = None) -> str:
    """Bind approval to the server's complete input/output contract."""
    if full_schema is not None:
        return snapshot_digest({"name": name, "schema": full_schema})
    return snapshot_digest({"name": name, "properties": properties, "required": sorted(required)})


def validate_external_destination(url: str) -> None:
    """Require a fixed public TLS authority, independent of OSS defaults."""
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or "{" in parsed.netloc or "}" in parsed.netloc):
        raise ValueError("live external tools require a fixed credential-free HTTPS authority")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("tool destination does not resolve") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("tool destination must resolve only to public addresses")


_TEMPLATE_VARIABLE = re.compile(r"\{\{\s*([^|\s}]+)")


def _template_variables(value: Any) -> set[str]:
    """Every ``{{ path }}`` a tool's templates read, at any nesting depth."""
    if isinstance(value, str):
        return set(_TEMPLATE_VARIABLE.findall(value))
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            found |= _template_variables(key) | _template_variables(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found |= _template_variables(item)
        return found
    return set()


def context_paths_used(config: dict[str, Any]) -> set[str]:
    """The call-context fields this tool's URL, presets and body ask for.

    Only the explicit ``initial_context.x`` / ``gathered_context.x`` form: a
    bare ``{{x}}`` may equally be an LLM argument or a preset, and guessing
    would reject valid tools.
    """
    sources: list[Any] = [config.get("url") or "", config.get("body_template")]
    sources += [param.get("value_template") for param in config.get("preset_parameters") or []]
    used: set[str] = set()
    for source in sources:
        used |= _template_variables(source)
    return {path for path in used
            if path.startswith(("initial_context.", "gathered_context."))}


def approved_context(source: dict[str, Any] | None, prefix: str,
                     allowed_paths: list[str]) -> dict[str, Any]:
    """Copy only reviewed context fields into an external tool request."""
    output: dict[str, Any] = {}
    for path in allowed_paths:
        if not path.startswith(prefix + "."):
            continue
        parts = path[len(prefix) + 1:].split(".")
        if any(not part for part in parts):
            continue
        value: Any = source or {}
        for part in parts:
            if not isinstance(value, dict) or part not in value:
                break
            value = value[part]
        else:
            target = output
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
    return output


def live_policy_error(policy: dict[str, Any], context: dict[str, Any],
                      challenge_verified: bool) -> str | None:
    if not policy:
        return None  # Legacy published calls retain their former guardrails.
    channel = "whatsapp" if context.get("channel") == "whatsapp" else context.get("direction")
    if channel not in policy.get("channels", []):
        return "tool_channel_not_approved"
    required = policy.get("min_identity")
    if required == "challenge" and not challenge_verified:
        return "identity_not_verified"
    if required == "endpoint" and not (challenge_verified or context.get("caller_known") is True
                                       or (channel in {"outbound", "whatsapp"} and context.get("customer_id"))):
        return "endpoint_identity_not_matched"
    return None


class LiveToolPolicy(BaseModel):
    risk: str
    channels: list[str]
    min_identity: str = "none"
    egress_fields: list[str] = Field(default_factory=list)
    success_path: str | None = None
    success_value: Any = True
    error_code_path: str | None = None
    idempotency_parameter: str | None = None
    allowed_mcp_functions: dict[str, str] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("risk")
    @classmethod
    def risk_valid(cls, value: str) -> str:
        if value not in {"read", "write", "platform"}:
            raise ValueError("risk must be read, write, or platform")
        return value

    @field_validator("channels")
    @classmethod
    def channels_valid(cls, value: list[str]) -> list[str]:
        if not value or set(value) - {"inbound", "outbound", "whatsapp"}:
            raise ValueError("choose at least one supported channel")
        return sorted(set(value))

    @field_validator("min_identity")
    @classmethod
    def identity_valid(cls, value: str) -> str:
        if value not in {"none", "endpoint", "challenge"}:
            raise ValueError("min_identity must be none, endpoint, or challenge")
        return value

    @model_validator(mode="after")
    def check_live_contract(self) -> "LiveToolPolicy":
        if self.risk in {"read", "write"} and not self.success_path:
            raise ValueError("live external tools require an explicit success path")
        if self.risk in {"read", "write"}:
            if not self.result_schema:
                raise ValueError("live external tools require a result JSON schema")
            Draft202012Validator.check_schema(self.result_schema)
        if self.risk == "write" and (not self.idempotency_parameter or not self.success_path):
            raise ValueError("live writes require an idempotency parameter and a success path")
        if self.risk == "write" and self.min_identity != "challenge":
            raise ValueError("live writes require challenge-level identity")
        if any(not field or field.startswith("*") or ".." in field for field in self.egress_fields):
            raise ValueError("egress fields must name explicit context paths")
        return self


def validate_live_snapshot(snapshot: dict[str, Any], policy: LiveToolPolicy) -> None:
    category = snapshot.get("category")
    config = (snapshot.get("definition") or {}).get("config") or {}
    if category in {"http_api", "mcp"} and policy.risk != "platform":
        validate_external_destination(str(config.get("url") or ""))
        for name in (config.get("headers") or {}):
            if str(name).lower() in {"authorization", "proxy-authorization", "cookie", "x-api-key"}:
                raise ValueError("secrets must use a credential reference, not a static header")
    if category == "mcp":
        discovered = {str(item.get("name")): item for item in config.get("discovered_tools") or []}
        if not policy.allowed_mcp_functions or set(policy.allowed_mcp_functions) - discovered.keys():
            raise ValueError("approve explicit functions from a successful MCP discovery")
        for name, digest in policy.allowed_mcp_functions.items():
            if not digest or discovered[name].get("schema_digest") != digest:
                raise ValueError(f"MCP function {name} has no matching discovered schema digest")
            if (policy.risk == "write" and policy.idempotency_parameter
                    not in (discovered[name].get("properties") or {})):
                raise ValueError(f"MCP write function {name} lacks the idempotency input")
    if category in {"http_api", "mcp"} and policy.risk in {"read", "write"}:
        # A reviewed tool is only sent the context fields the reviewer listed.
        # Anything else its templates read renders blank at call time — an
        # empty field posted to the customer's API, or a required preset that
        # fails every call. Catch it here, while someone is still looking.
        missing = context_paths_used(config) - set(policy.egress_fields)
        if missing:
            raise ValueError(
                "approve the context fields these templates read, or stop reading them: "
                + ", ".join(sorted(missing))
            )
    if category == "http_api" and policy.risk == "write":
        if str(config.get("method") or "").upper() not in {"POST", "PUT", "PATCH"}:
            raise ValueError("live writes require POST, PUT, or PATCH")
        parameters = {str(p.get("name")) for p in config.get("parameters") or []}
        presets = {str(p.get("name")) for p in config.get("preset_parameters") or []}
        if policy.idempotency_parameter not in parameters | presets:
            raise ValueError("idempotency parameter is missing from the tool schema")
