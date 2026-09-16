"""What an eval report was run against, as one key.

``eval_reports.prompt_version_id`` says which row a suite ran on. It is the
wrong identity for the gate's question -- "has *this content* passed?" -- in
both directions: a draft restored from a passed version is a new row with the
same words and no report, and a version whose persona was edited after its
run keeps the row id and the green report.

``content_key`` is the sha256 of everything that changes what the mouth says
or may do: the card, the flow, the prompt, the persona, the guardrails, the
voice, the tuning, the attached skill packs by content hash, and the grader
version. G7/G8/G-OB9 accept a stored pass with the same key -- a republish of
identical content is not re-judged -- and refuse one with a different key
however recent. G-F14 reports the provenance itself.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable
from agent_core.dicts import sub

#: Bump when a grader's verdict semantics change; every stored pass then
#: needs a re-run, which is the point.
GRADER_VERSION = "graders-v2"


def _normalize(value: Any) -> Any:
    """Drop JSON number-type noise so a browser round-trip is the same content.

    ``json.dumps(1.0)`` is ``1.0`` and ``JSON.stringify(1.0)`` is ``1``. The
    studio mapper stores ``voice.speed`` as a float; the editor sends it back
    as an int. Hashing the type tag made G-F14 fail on an unchanged save.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def _canon(value: Any) -> str:
    return json.dumps(
        _normalize(value if value is not None else {}),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def content_key(
    *,
    card: Any,
    flow: Any,
    prompt: str | None,
    persona: Any,
    guardrails: Any,
    voice: Any,
    tuning: Any,
    skill_packs: Iterable[Any] = (),
) -> str:
    """The identity of what a suite would judge. Deterministic; no DB."""
    packs = sorted(
        f"{getattr(p, 'slug', '')}@{getattr(p, 'version', '')}:{getattr(p, 'content_hash', '')}"
        for p in skill_packs
    )
    parts = [
        _canon(card),
        _canon(flow),
        (prompt or "").strip(),
        _canon(persona),
        _canon(guardrails),
        _canon(voice),
        _canon(tuning),
        _canon(packs),
        GRADER_VERSION,
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def content_key_for_version(version: dict[str, Any]) -> str:
    """The key of a stored ``prompt_versions`` row, packs resolved as the
    runtime would resolve them."""
    packs: list[Any] = []
    try:
        from agent_core.cards.schema import is_authored, parse_card
        from agent_core.skills.persist import packs_for_skill_refs

        raw = sub(version, "agentCard")
        if is_authored(raw):
            packs = packs_for_skill_refs(parse_card(raw).skills)
    except Exception:
        packs = []
    return content_key(
        card=version.get("agentCard") or {},
        flow=version.get("flow") or {},
        prompt=version.get("prompt"),
        persona=version.get("persona"),
        guardrails=version.get("guardrails"),
        voice=version.get("voice"),
        tuning=version.get("tuning"),
        skill_packs=packs,
    )
