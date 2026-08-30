"""Parse an Agent Skill pack (SKILL.md + optional references/).

Frontmatter is a small YAML subset so we do not take PyYAML on the mouth path.
Unknown keys are kept in ``raw`` for round-trip; required keys are validated
by ``lint.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKS_DIR = Path(__file__).resolve().parent / "packs"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class SkillPack:
    slug: str
    description: str
    allowed_tools: list[str]
    body: str
    version: str = "1.0.0"
    data_class: list[str] = field(default_factory=list)
    eval_suite: str | None = None
    mouth: list[str] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    origin: str = "first_party"
    signed: bool = True

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "frontmatter": self.frontmatter,
                "body": self.body,
                "references": self.references,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approx_tokens(text: str) -> int:
    """Cheap, stable token estimate (chars/4). Used by G6, never billed."""
    stripped = (text or "").strip()
    if not stripped:
        return 0
    return max(1, (len(stripped) + 3) // 4)


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value in {"[]", ""}:
        return [] if value == "[]" else ""
    # `null` / `~` are how `_emit_scalar` writes None, and how YAML spells it.
    # Without this, a null came back as the four-character string "None" — see
    # the note on `_emit_scalar`.
    if value.lower() in {"null", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def parse_frontmatter_yaml(block: str) -> dict[str, Any]:
    """Indent-based mapping / list parser covering our SKILL.md subset."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending_list_key: str | None = None

    for raw_line in block.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
            pending_list_key = None
        parent = stack[-1][1]

        if line.startswith("- "):
            item = _parse_scalar(line[2:])
            if pending_list_key is not None and len(stack) >= 2:
                grandparent = stack[-2][1]
                inner = stack[-1][1]
                if isinstance(grandparent, dict) and grandparent.get(pending_list_key) is inner:
                    lst: list[Any] = []
                    grandparent[pending_list_key] = lst
                    stack[-1] = (stack[-1][0], lst)
                    pending_list_key = None
                    parent = lst
            if isinstance(parent, list):
                parent.append(item)
            continue

        if ":" not in line or not isinstance(parent, dict):
            continue
        key, rest = line.split(":", 1)
        key, rest = key.strip(), rest.strip()
        pending_list_key = None
        if rest == "":
            parent[key] = {}
            stack.append((indent, parent[key]))
            pending_list_key = key
        else:
            parent[key] = _parse_scalar(rest)
    return root


def split_skill_md(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("skill_missing_frontmatter")
    meta = parse_frontmatter_yaml(match.group(1))
    body = text[match.end() :].strip()
    return meta, body


def parse_skill_md(text: str, *, slug_hint: str | None = None) -> SkillPack:
    meta, body = split_skill_md(text)
    slug = str(meta.get("name") or slug_hint or "").strip()
    if not slug:
        raise ValueError("skill_missing_name")
    allowed = meta.get("allowed-tools") or meta.get("allowed_tools") or []
    if not isinstance(allowed, list):
        raise ValueError("skill_allowed_tools_not_a_list")
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    data_class = metadata.get("data_class") or []
    if not isinstance(data_class, list):
        data_class = [str(data_class)]
    mouth = metadata.get("mouth") or []
    if not isinstance(mouth, list):
        mouth = [str(mouth)]
    return SkillPack(
        slug=slug,
        description=str(meta.get("description") or "").strip(),
        allowed_tools=[str(t).strip() for t in allowed if str(t).strip()],
        body=body,
        version=str(metadata.get("version") or "1.0.0"),
        data_class=[str(x) for x in data_class],
        eval_suite=str(metadata.get("eval_suite") or "") or None,
        mouth=[str(x) for x in mouth],
        frontmatter=meta,
    )


def load_pack_dir(path: Path, *, origin: str = "first_party", signed: bool = True) -> SkillPack:
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"skill_md_missing:{path}")
    pack = parse_skill_md(skill_md.read_text(encoding="utf-8"), slug_hint=path.name)
    pack.origin = origin
    pack.signed = signed
    refs_dir = path / "references"
    if refs_dir.is_dir():
        for ref in sorted(refs_dir.rglob("*")):
            if ref.is_file():
                rel = ref.relative_to(refs_dir).as_posix()
                pack.references[rel] = ref.read_text(encoding="utf-8")
    examples = path / "examples.jsonl"
    if examples.is_file():
        for line in examples.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            pack.examples.append(json.loads(line))
    return pack


def iter_first_party_packs() -> list[SkillPack]:
    if not PACKS_DIR.is_dir():
        return []
    packs: list[SkillPack] = []
    for child in sorted(PACKS_DIR.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            packs.append(load_pack_dir(child, origin="first_party", signed=True))
    return packs


def pack_for_slug(slug: str) -> SkillPack:
    path = PACKS_DIR / slug
    if not path.is_dir():
        raise KeyError(f"unknown_first_party_skill:{slug}")
    return load_pack_dir(path, origin="first_party", signed=True)


def _emit_scalar(value: Any) -> str:
    """Render one frontmatter scalar in YAML, not in Python's repr.

    Every scalar used to go out through `f"{key}: {value}"`, which means
    `str(value)` — so `None` was written as the four characters `None` and read
    back by `_parse_scalar` as the STRING "None". Gardener sets
    `metadata.eval_suite = None` on every draft it creates, meaning "there is no
    eval suite for this", and each of those drafts stored, hashed, signed and
    exported a claim to have an eval suite named `None`.

    Booleans had the same defect and got away with it: `str(True)` is `True`,
    which only round-trips because `_parse_scalar` lowercases before comparing.
    Relying on that is how the None case survived unnoticed, so both are written
    explicitly here.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def dumps_skill_md(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body. Used by gardener drafts and the editor save path."""
    lines = ["---"]

    def emit(obj: Any, indent: int) -> None:
        pad = "  " * indent
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, dict):
                    lines.append(f"{pad}{key}:")
                    emit(value, indent + 1)
                elif isinstance(value, list):
                    if not value:
                        lines.append(f"{pad}{key}: []")
                    else:
                        lines.append(f"{pad}{key}:")
                        for item in value:
                            lines.append(f"{pad}  - {_emit_scalar(item)}")
                else:
                    lines.append(f"{pad}{key}: {_emit_scalar(value)}")

    emit(frontmatter, 0)
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    lines.append("")
    return "\n".join(lines)
