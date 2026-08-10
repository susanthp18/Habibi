"""Text chunking (tiktoken) + FAQ Q/A parsing for the Knowledge Base."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import tiktoken

# cl100k_base is the tokenizer family used by text-embedding-3-* / GPT-4o-class models.
_ENCODING_NAME = "cl100k_base"


def _enc():
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    return len(_enc().encode(text or ""))


@dataclass(frozen=True)
class ChunkDraft:
    index: int
    heading: str
    text: str
    tokens: int


@dataclass(frozen=True)
class FaqDraft:
    question: str
    answer: str


def chunk_text(
    text: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
    default_heading: str = "Body",
) -> list[ChunkDraft]:
    """Split text into ~chunk_size token windows with overlap. Prefer heading-aware MD when possible."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    sections = _split_markdown_sections(text, default_heading=default_heading)
    drafts: list[ChunkDraft] = []
    enc = _enc()

    for heading, body in sections:
        body = body.strip()
        if not body:
            continue
        token_ids = enc.encode(body)
        if len(token_ids) <= chunk_size:
            drafts.append(
                ChunkDraft(
                    index=len(drafts) + 1,
                    heading=heading,
                    text=body,
                    tokens=len(token_ids),
                )
            )
            continue

        start = 0
        part = 1
        while start < len(token_ids):
            end = min(start + chunk_size, len(token_ids))
            piece = enc.decode(token_ids[start:end]).strip()
            if piece:
                label = heading if part == 1 else f"{heading} · §{part}"
                drafts.append(
                    ChunkDraft(
                        index=len(drafts) + 1,
                        heading=label,
                        text=piece,
                        tokens=end - start,
                    )
                )
                part += 1
            if end >= len(token_ids):
                break
            start = max(0, end - overlap)

    return drafts


def _split_markdown_sections(text: str, *, default_heading: str) -> list[tuple[str, str]]:
    """Split on ATX headings (# .. ######). Plain text → single section."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    sections: list[tuple[str, list[str]]] = []
    current_heading = default_heading
    current_lines: list[str] = []

    for line in lines:
        m = heading_re.match(line)
        if m:
            if current_lines and any(s.strip() for s in current_lines):
                sections.append((current_heading, current_lines))
            current_heading = m.group(2).strip() or default_heading
            current_lines = []
            continue
        current_lines.append(line)

    if current_lines and any(s.strip() for s in current_lines):
        sections.append((current_heading, current_lines))

    if not sections:
        return [(default_heading, text or "")]
    return [(h, "\n".join(body_lines)) for h, body_lines in sections]


def parse_faq_qa(text: str) -> list[FaqDraft]:
    """Parse Q:/A: FAQ files. Multi-line answers until the next Q:."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    pairs: list[FaqDraft] = []
    question: str | None = None
    answer_lines: list[str] = []

    def flush() -> None:
        nonlocal question, answer_lines
        if question is None:
            return
        answer = "\n".join(answer_lines).strip()
        q = question.strip()
        if q and answer:
            pairs.append(FaqDraft(question=q, answer=answer))
        question = None
        answer_lines = []

    for raw in lines:
        line = raw.rstrip()
        if line.upper().startswith("Q:"):
            flush()
            question = line[2:].strip()
            answer_lines = []
        elif line.upper().startswith("A:"):
            if question is None:
                continue
            answer_lines.append(line[2:].strip())
        else:
            if question is not None and answer_lines:
                answer_lines.append(line)

    flush()
    return pairs


def faq_intent(product_key: str, question: str) -> str:
    """Stable intent key for an FAQ question.

    Normalises case and internal whitespace first so re-formatting a question
    in the source corpus does not mint a new intent for the same content, and
    uses sha256 with a wider slice — 8 hex chars (32 bits) collides at roughly
    a few thousand entries by the birthday bound, which a growing FAQ corpus
    reaches.
    """
    normalized = " ".join((question or "").lower().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{product_key}.{digest}"


def faq_id(product_key: str, index: int) -> str:
    return f"faq-{product_key}-{index:03d}"
