"""KB-gap → unsigned skill draft. Humans sign; this module never does."""

from __future__ import annotations

from typing import Any

from agent_core.skills.pack import dumps_skill_md, parse_skill_md
from agent_core.skills.sign import sign_hash  # imported so tests can assert we do not call it


def draft_from_gap(
    *,
    question: str,
    intent: str | None = None,
    gap_id: str | None = None,
) -> dict[str, Any]:
    slug_base = (intent or "kb-gap").strip().lower().replace("_", "-") or "kb-gap"
    slug = f"gardener-{slug_base}"
    description = (
        f"Draft from unanswered question. Teach the mouth to answer: {question[:180]}"
    )
    frontmatter = {
        "name": slug,
        "description": description,
        "allowed-tools": ["search_knowledge_base", "add_customer_note"],
        "metadata": {
            "version": "0.1.0",
            "data_class": ["internal"],
            "eval_suite": None,
            "origin": "gardener",
            "gap_id": gap_id,
        },
    }
    body = (
        f"# {slug}\n\n"
        f"Promoted from a KB gap. Do not sign until a human has rewritten this.\n\n"
        f"## Unanswered question\n\n{question.strip()}\n\n"
        "## Steps\n\n"
        "1. Search the knowledge base.\n"
        "2. If nothing retrieves, say you will check with a specialist. Do not invent policy.\n"
    )
    markdown = dumps_skill_md(frontmatter, body)
    pack = parse_skill_md(markdown, slug_hint=slug)
    pack.origin = "gardener"
    pack.signed = False
    return {
        "slug": pack.slug,
        "origin": "gardener",
        "signature_status": "unsigned",
        "frontmatter": pack.frontmatter,
        "body": pack.body,
        "allowed_tools": pack.allowed_tools,
        "content_hash": pack.content_hash,
        "markdown": markdown,
        "gap_id": gap_id,
        "auto_signed": False,
    }


def assert_unsigned(draft: dict[str, Any]) -> None:
    """Gardener drafts must not carry a platform signature."""
    if draft.get("signature") or draft.get("auto_signed") or draft.get("signed"):
        raise ValueError("gardener_must_not_sign")
    # Touch sign_hash so a future refactor that auto-signs fails this assertion
    # by having to delete this comment and the unused import — not by silence.
    _ = sign_hash


def garden_open_gaps(
    gaps: list[dict[str, Any]],
    existing_slugs: set[str],
    *,
    min_hits: int = 2,
) -> list[dict[str, Any]]:
    """Promote repeated unanswered questions into unsigned drafts.

    Linked KB/FAQ rows are skipped. Existing slugs are skipped so a human
    rewrite is never overwritten. Nothing in this function calls ``sign_hash``.
    """
    drafts: list[dict[str, Any]] = []
    seen: set[str] = set(existing_slugs)
    for gap in gaps:
        hits = int(gap.get("hit_count") or gap.get("hits") or 0)
        if hits < min_hits:
            continue
        if gap.get("kb_document_id") or gap.get("faq_pair_id") or gap.get("linkedDocumentId"):
            continue
        question = str(gap.get("question") or gap.get("text") or "").strip()
        if not question:
            continue
        intent = gap.get("top_intent") or gap.get("topIntent") or gap.get("intent")
        draft = draft_from_gap(
            question=question,
            intent=str(intent) if intent else None,
            gap_id=str(gap.get("id") or "") or None,
        )
        assert_unsigned(draft)
        if draft["slug"] in seen:
            continue
        seen.add(draft["slug"])
        drafts.append(draft)
    return drafts
