"""Skill catalog persistence — signed versions, attachments, gardener drafts."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text

import db
from agent_core.skills.lint import assert_pack_lints
from agent_core.skills.pack import SkillPack, approx_tokens, dumps_skill_md, parse_skill_md
from agent_core.skills.sign import sign_hash, verify_signature

logger = logging.getLogger(__name__)


def _stored_version(pack_version: str) -> str:
    return "1" if pack_version in {"1", "1.0.0"} else pack_version


def _bump_version(version: str) -> str:
    stored = _stored_version(version)
    if "." not in stored:
        return f"{stored}.1"
    parts = stored.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except ValueError:
        return f"{stored}.1"


def _version_row_id(skill_id: str, version: str) -> str:
    return f"{skill_id}-v{version.replace('.', '_')}"


def _map_skill(row: dict[str, Any], *, versions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    latest = None
    if versions:
        latest = next((v for v in versions if v["id"] == row.get("latest_version_id")), versions[0])
    allowed = []
    if latest:
        allowed = list(latest.get("allowedTools") or latest.get("allowed_tools") or [])
    return {
        "id": row["id"],
        "slug": row["slug"],
        "origin": row["origin"],
        "signatureStatus": row["signature_status"],
        "latestVersionId": row.get("latest_version_id"),
        "description": (latest or {}).get("description") or "",
        "allowedTools": allowed,
        "version": (latest or {}).get("version") or "1",
        "status": (latest or {}).get("status") or row["signature_status"],
        "attachedCards": row.get("attached_cards") or [],
        "evalSuite": (latest or {}).get("evalSuite"),
        "contentHash": (latest or {}).get("contentHash") or "",
        "signed": row["signature_status"] == "signed",
        "hasSignedVersion": bool(row.get("has_signed") or row["signature_status"] == "signed"),
        "bodyTokens": approx_tokens((latest or {}).get("body") or ""),
        "referenceFiles": list(((latest or {}).get("pack") or {}).get("references") or {}),
    }


def _map_version(row: dict[str, Any]) -> dict[str, Any]:
    fm = row.get("frontmatter") if isinstance(row.get("frontmatter"), dict) else {}
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    allowed = row.get("allowed_tools") or []
    if hasattr(allowed, "tolist"):
        allowed = list(allowed)
    return {
        "id": row["id"],
        "skillId": row["skill_id"],
        "version": row["version"],
        "status": row["status"],
        "frontmatter": fm,
        "body": row.get("body") or "",
        "allowedTools": list(allowed),
        "contentHash": row.get("content_hash") or "",
        "signature": row.get("signature"),
        "signedBy": row.get("signed_by"),
        "pack": row.get("pack") if isinstance(row.get("pack"), dict) else {},
        "description": str(fm.get("description") or ""),
        "evalSuite": meta.get("eval_suite"),
        "origin": meta.get("origin"),
    }


def pack_from_version_row(row: dict[str, Any], *, origin: str, signed: bool) -> SkillPack:
    mapped = _map_version(row)
    md = dumps_skill_md(mapped["frontmatter"] or {"name": "skill", "description": "", "allowed-tools": []}, mapped["body"])
    pack = parse_skill_md(md)
    pack.origin = origin
    pack.signed = signed and bool(mapped.get("signature")) and verify_signature(
        mapped["contentHash"], mapped.get("signature")
    )
    pack.references = (mapped.get("pack") or {}).get("references") or {}
    return pack


def list_skills(*, _synced: bool = False) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        skills = db._rows(
            conn.execute(
                text(
                    """
                    SELECT s.id, s.slug, s.origin, s.signature_status, s.latest_version_id,
                           EXISTS (
                             SELECT 1 FROM skill_versions svs
                              WHERE svs.skill_id = s.id AND svs.status = 'signed'
                           ) AS has_signed,
                           -- Archived cards are not attachments.
                           --
                           -- The status filter kept only published versions but
                           -- said nothing about whether the CARD is still in
                           -- service, so the library's "Attached: ..." line
                           -- cited retired cards — e2e-audit-card-8216c4,
                           -- archived on 2026-08-19, listed as a live consumer
                           -- of a first-party skill. That is the number an
                           -- operator checks before deleting or re-signing a
                           -- skill, so an inflated one is the kind that stops
                           -- work that should have gone ahead.
                           COALESCE((
                             SELECT json_agg(DISTINCT pv.bot_id)
                               FROM skill_attachments sa
                               JOIN skill_versions sv ON sv.id = sa.skill_version_id
                               JOIN prompt_versions pv ON pv.id = sa.prompt_version_id
                               LEFT JOIN bots b ON b.id = pv.bot_id
                                                AND b.tenant_id = pv.tenant_id
                              WHERE sv.skill_id = s.id
                                AND pv.status = 'published'
                                AND b.archived_at IS NULL
                           ), '[]'::json) AS attached_cards
                      FROM skills s
                     WHERE s.tenant_id = :tenant
                     ORDER BY s.slug
                    """
                ),
                {"tenant": db._tenant()},
            )
        )
        versions = {
            v["id"]: v
            for v in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT sv.*
                          FROM skill_versions sv
                          JOIN skills s ON s.id = sv.skill_id
                         WHERE s.tenant_id = :tenant
                        """
                    ),
                    {"tenant": db._tenant()},
                )
            )
        }
    out = []
    for row in skills:
        latest = versions.get(row["latest_version_id"] or "")
        mapped_latest = _map_version(latest) if latest else None
        cards = row.get("attached_cards") or []
        if isinstance(cards, str):
            try:
                cards = json.loads(cards)
            except json.JSONDecodeError:
                cards = []
        row = {**row, "attached_cards": cards}
        item = _map_skill(row, versions=[mapped_latest] if mapped_latest else None)
        if mapped_latest:
            item["description"] = mapped_latest["description"]
            item["allowedTools"] = mapped_latest["allowedTools"]
            item["version"] = mapped_latest["version"]
            item["status"] = mapped_latest["status"]
            item["contentHash"] = mapped_latest["contentHash"]
            item["evalSuite"] = mapped_latest["evalSuite"]
        out.append(item)
    if not out and not _synced:
        try:
            ensure_first_party_skills()
        except Exception:
            logger.exception("skill catalog boot-sync from empty list failed")
            return out
        return list_skills(_synced=True)
    return out


def get_skill(skill_id: str) -> dict[str, Any] | None:
    items = [s for s in list_skills() if s["id"] == skill_id or s["slug"] == skill_id]
    if not items:
        return None
    summary = items[0]
    with db.engine.connect() as conn:
        versions = db._rows(
            conn.execute(
                text(
                    """
                    SELECT sv.*
                      FROM skill_versions sv
                     WHERE sv.skill_id = :id
                     ORDER BY sv.created_at DESC
                    """
                ),
                {"id": summary["id"]},
            )
        )
    summary["versions"] = [_map_version(v) for v in versions]
    latest = next((v for v in summary["versions"] if v["id"] == summary["latestVersionId"]), None)
    if latest:
        summary["frontmatter"] = latest["frontmatter"]
        summary["body"] = latest["body"]
        summary["pack"] = latest["pack"]
        summary["markdown"] = dumps_skill_md(latest["frontmatter"], latest["body"])
    return summary


def upsert_skill_from_pack(
    pack: SkillPack,
    *,
    origin: str | None = None,
    signed: bool = False,
    signed_by: str | None = None,
    skill_id: str | None = None,
    set_latest: bool | None = None,
) -> dict[str, Any]:
    origin = origin or pack.origin
    # Every write into the skill catalog funnels through here — the studio POST,
    # the editor PATCH, the .md/.zip import, gardener drafts, first-party
    # seeding. Linting at this choke point is what stops an unknown allowed-tool
    # becoming a stored version that can only ever fail G9.
    warnings = assert_pack_lints(pack)
    sid = skill_id or f"skill-{pack.slug}"
    stored_version = _stored_version(pack.version)
    signature = sign_hash(pack.content_hash) if signed else None
    status = "signed" if signed and signature else "draft"
    sig_status = "signed" if status == "signed" else "unsigned"
    pack_json = {
        "references": pack.references,
        "examples": pack.examples,
    }
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO skills (id, tenant_id, slug, signature_status, origin)
                VALUES (:id, :tenant, :slug, :sig, :origin)
                ON CONFLICT (tenant_id, slug) DO UPDATE
                  SET origin = CASE
                        WHEN skills.origin IN ('tenant', 'gardener') THEN skills.origin
                        ELSE EXCLUDED.origin
                      END
                """
            ),
            {
                "id": sid,
                "tenant": db._tenant(),
                "slug": pack.slug,
                "sig": sig_status,
                "origin": origin,
            },
        )
        existing = db._one(
            conn.execute(
                text("SELECT id, latest_version_id, origin FROM skills WHERE tenant_id = :t AND slug = :s"),
                {"t": db._tenant(), "s": pack.slug},
            )
        )
        sid = existing["id"] if existing else sid
        vid = _version_row_id(sid, stored_version)
        conn.execute(
            text(
                """
                INSERT INTO skill_versions (
                  id, skill_id, version, status, frontmatter, body, allowed_tools,
                  content_hash, signature, signed_by, pack
                ) VALUES (
                  :id, :skill_id, :version, :status, CAST(:fm AS jsonb), :body, CAST(:tools AS text[]),
                  :hash, :signature, :signed_by, CAST(:pack AS jsonb)
                )
                ON CONFLICT (skill_id, version) DO UPDATE SET
                  status = EXCLUDED.status,
                  frontmatter = EXCLUDED.frontmatter,
                  body = EXCLUDED.body,
                  allowed_tools = EXCLUDED.allowed_tools,
                  content_hash = EXCLUDED.content_hash,
                  signature = EXCLUDED.signature,
                  signed_by = EXCLUDED.signed_by,
                  pack = EXCLUDED.pack
                """
            ),
            {
                "id": vid,
                "skill_id": sid,
                "version": stored_version,
                "status": status,
                "fm": db._jsonb(pack.frontmatter),
                "body": pack.body,
                "tools": "{" + ",".join(pack.allowed_tools) + "}",
                "hash": pack.content_hash,
                "signature": signature,
                "signed_by": signed_by,
                "pack": db._jsonb(pack_json),
            },
        )
        if set_latest is None:
            set_latest = True
        if set_latest:
            conn.execute(
                text("UPDATE skills SET latest_version_id = :vid, signature_status = :sig WHERE id = :id"),
                {"vid": vid, "sig": sig_status, "id": sid},
            )
    saved = get_skill(sid) or {"id": sid, "slug": pack.slug}
    if warnings:
        logger.warning("skill %s saved with lint warnings: %s", pack.slug, warnings)
        saved["lintWarnings"] = warnings
    return saved


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slug_exists(slug: str) -> bool:
    with db.engine.connect() as conn:
        return bool(
            db._one(
                conn.execute(
                    text("SELECT 1 FROM skills WHERE tenant_id = :t AND slug = :s"),
                    {"t": db._tenant(), "s": slug},
                )
            )
        )


def unique_slug(base: str) -> str:
    """`base`, else base-2, base-3… Cloning twice used to reuse one slug, and
    upsert_skill_from_pack keys on (tenant, slug) — so the second clone
    overwrote the first and reset it to unsigned."""
    candidate = base
    n = 1
    while slug_exists(candidate):
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def create_draft_skill(payload: dict[str, Any]) -> dict[str, Any]:
    slug = str(payload.get("slug") or payload.get("name") or "").strip().lower()
    if not slug:
        raise ValueError("skill_slug_required")
    if not _SLUG_RE.match(slug):
        raise ValueError("skill_slug_invalid")
    # upsert_skill_from_pack keys on (tenant_id, slug) and resets
    # signature_status, so creating over an existing slug silently unsigned a
    # first-party pack and replaced its body. Creation must not be an upsert.
    if slug_exists(slug):
        raise ValueError("skill_slug_taken")
    allowed = payload.get("allowedTools") or payload.get("allowed_tools") or []
    if not isinstance(allowed, list):
        raise ValueError("allowed_tools_must_be_list")
    description = str(payload.get("description") or "").strip()
    body = str(payload.get("body") or "").strip()
    frontmatter = payload.get("frontmatter") if isinstance(payload.get("frontmatter"), dict) else {
        "name": slug,
        "description": description,
        "allowed-tools": allowed,
        "metadata": {"version": "0.1.0", "origin": payload.get("origin") or "tenant"},
    }
    md = dumps_skill_md(frontmatter, body or f"# {slug}\n")
    pack = parse_skill_md(md, slug_hint=slug)
    pack.origin = str(payload.get("origin") or "tenant")
    pack.signed = False
    # Refuse an unknown or malformed allowed-tools list before the write. The
    # upsert lints too; running it here keeps the rejection on the payload the
    # caller sent rather than on a stored version.
    assert_pack_lints(pack)
    return upsert_skill_from_pack(pack, origin=pack.origin, signed=False)


def patch_skill(skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_skill(skill_id)
    if current is None:
        raise KeyError("skill_not_found")
    latest = next(
        (v for v in (current.get("versions") or []) if v["id"] == current.get("latestVersionId")),
        (current.get("versions") or [None])[0],
    )
    frontmatter = payload.get("frontmatter") if isinstance(payload.get("frontmatter"), dict) else current.get("frontmatter") or {}
    if "description" in payload:
        frontmatter = {**frontmatter, "description": payload["description"]}
    if "allowedTools" in payload or "allowed_tools" in payload:
        tools = payload.get("allowedTools") or payload.get("allowed_tools")
        frontmatter = {**frontmatter, "allowed-tools": tools}
    if "slug" in payload:
        frontmatter = {**frontmatter, "name": payload["slug"]}
    body = payload["body"] if "body" in payload else current.get("body") or ""
    md = dumps_skill_md(frontmatter, body)
    pack = parse_skill_md(md, slug_hint=current["slug"])
    pack.origin = current["origin"]
    pack.signed = False
    if payload.get("version"):
        pack.version = str(payload["version"])
    elif latest and latest.get("status") == "signed":
        pack.version = _bump_version(str(latest.get("version") or "1"))
    elif latest:
        pack.version = str(latest.get("version") or "0.1.1")
    else:
        pack.version = "0.1.1"
    return upsert_skill_from_pack(pack, origin=pack.origin, signed=False, skill_id=current["id"])


def sign_skill(skill_id: str) -> dict[str, Any]:
    """Sign the current latest version in place. Never overwrites an older signed row."""
    current = get_skill(skill_id)
    if current is None:
        raise KeyError("skill_not_found")
    latest_id = current.get("latestVersionId")
    latest = next((v for v in (current.get("versions") or []) if v["id"] == latest_id), None)
    if latest is None:
        raise ValueError("skill_has_no_version")
    if latest.get("status") == "signed" and verify_signature(latest.get("contentHash") or "", latest.get("signature")):
        return current
    signature = sign_hash(latest.get("contentHash") or "")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE skill_versions
                   SET status = 'signed',
                       signature = :sig,
                       signed_by = :by
                 WHERE id = :id
                """
            ),
            {"sig": signature, "by": db._actor_user_id(), "id": latest["id"]},
        )
        conn.execute(
            text("UPDATE skills SET signature_status = 'signed' WHERE id = :id"),
            {"id": current["id"]},
        )
    return get_skill(skill_id) or current


def revert_skill(skill_id: str, version_id: str | None = None) -> dict[str, Any]:
    """Point latest at a signed version. Drafts stay in history; production does not lose them."""
    current = get_skill(skill_id)
    if current is None:
        raise KeyError("skill_not_found")
    versions = current.get("versions") or []
    if version_id:
        target = next((v for v in versions if v["id"] == version_id), None)
    else:
        target = next((v for v in versions if v.get("status") == "signed"), None)
    if target is None or target.get("status") != "signed":
        raise ValueError("skill_revert_requires_signed_version")
    if not verify_signature(target.get("contentHash") or "", target.get("signature")):
        raise ValueError("skill_signature_invalid")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE skills
                   SET latest_version_id = :vid,
                       signature_status = 'signed'
                 WHERE id = :id
                """
            ),
            {"vid": target["id"], "id": current["id"]},
        )
    return get_skill(skill_id) or current


def clone_skill(source_id: str, new_slug: str | None = None) -> dict[str, Any]:
    """Copy a skill into an unsigned tenant row. Marketplace import stays signed."""
    src = get_skill(source_id)
    if src is None:
        raise KeyError("skill_not_found")
    requested = (new_slug or "").strip().lower()
    if requested and not _SLUG_RE.match(requested):
        raise ValueError("skill_slug_invalid")
    if requested and slug_exists(requested):
        raise ValueError("skill_slug_taken")
    # An explicit slug is the caller's problem (above); a generated one must not
    # collide, or the clone would overwrite the previous clone.
    slug = requested or unique_slug(f"{src['slug']}-clone")
    frontmatter = dict(src.get("frontmatter") or {})
    frontmatter["name"] = slug
    return create_draft_skill(
        {
            "slug": slug,
            "description": src.get("description") or "",
            "allowedTools": list(src.get("allowedTools") or []),
            "body": src.get("body") or "",
            "frontmatter": frontmatter,
            "origin": "tenant",
        }
    )


def delete_skill(skill_id: str) -> dict[str, Any]:
    """Delete a tenant-authored skill. Refuses anything production depends on.

    Three guards, all fail-closed:
      * first-party packs are re-seeded on API boot, so deleting one is a no-op
        that looks like a success until the next restart;
      * a signed skill may be pinned by a published card — G9 resolves by slug,
        and a missing pack silently drops the mouth's tools;
      * an attached skill is in use by some prompt version right now.
    """
    current = get_skill(skill_id)
    if current is None:
        raise KeyError("skill_not_found")
    if current.get("origin") not in ("tenant", "gardener"):
        raise ValueError("skill_first_party_not_deletable")
    if current.get("signed") or current.get("hasSignedVersion"):
        raise ValueError("skill_signed_not_deletable")
    sid = current["id"]
    # `attachedCards` counts published versions only, which is right for the
    # fleet badge and wrong as a delete guard: a skill pinned by an unpublished
    # draft reported zero attachments, so deleting it left that draft naming a
    # pack that no longer exists — G9 then fails at publish with `unresolved`,
    # long after the delete, with nothing pointing at the cause.
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT pv.bot_id, pv.status
                      FROM skill_attachments sa
                      JOIN skill_versions sv ON sv.id = sa.skill_version_id
                      JOIN prompt_versions pv ON pv.id = sa.prompt_version_id
                     WHERE sv.skill_id = :id AND pv.status IN ('published', 'draft')
                    """
                ),
                {"id": sid},
            )
        )
    attached = sorted({f"{r['bot_id']} ({r['status']})" for r in rows})
    if attached:
        raise ValueError(f"skill_attached:{','.join(attached)}")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM skill_attachments sa
                 USING skill_versions sv
                 WHERE sa.skill_version_id = sv.id AND sv.skill_id = :id
                """
            ),
            {"id": sid},
        )
        # latest_version_id references skill_versions — clear it before the rows go.
        conn.execute(
            text("UPDATE skills SET latest_version_id = NULL WHERE id = :id"),
            {"id": sid},
        )
        conn.execute(text("DELETE FROM skill_versions WHERE skill_id = :id"), {"id": sid})
        conn.execute(
            text("DELETE FROM skills WHERE id = :id AND tenant_id = :t"),
            {"id": sid, "t": db._tenant()},
        )
    return {"ok": True, "id": sid, "slug": current["slug"]}


def _latest_signed_version(conn: Any, skill_id: str | None = None, slug: str | None = None) -> dict[str, Any] | None:
    if skill_id:
        return db._one(
            conn.execute(
                text(
                    """
                    SELECT sv.*, s.origin, s.signature_status, s.slug, s.id AS skill_pk
                      FROM skills s
                      JOIN skill_versions sv ON sv.skill_id = s.id
                     WHERE s.tenant_id = :tenant
                       AND s.id = :id
                       AND sv.status = 'signed'
                     ORDER BY sv.created_at DESC
                     LIMIT 1
                    """
                ),
                {"tenant": db._tenant(), "id": skill_id},
            )
        )
    if slug:
        return db._one(
            conn.execute(
                text(
                    """
                    SELECT sv.*, s.origin, s.signature_status, s.slug, s.id AS skill_pk
                      FROM skills s
                      JOIN skill_versions sv ON sv.skill_id = s.id
                     WHERE s.tenant_id = :tenant
                       AND s.slug = :slug
                       AND sv.status = 'signed'
                     ORDER BY sv.created_at DESC
                     LIMIT 1
                    """
                ),
                {"tenant": db._tenant(), "slug": slug},
            )
        )
    return None


def attach_skill_to_prompt(prompt_version_id: str, skill_id: str) -> None:
    skill = get_skill(skill_id)
    if skill is None:
        raise KeyError("skill_not_found")
    with db.engine.begin() as conn:
        signed = _latest_signed_version(conn, skill_id=skill["id"])
        if signed is None:
            raise ValueError("skill_unsigned")
        conn.execute(
            text(
                """
                INSERT INTO skill_attachments (prompt_version_id, skill_version_id)
                VALUES (:pv, :sv)
                ON CONFLICT DO NOTHING
                """
            ),
            {"pv": prompt_version_id, "sv": signed["id"]},
        )


def detach_skill_from_prompt(prompt_version_id: str, skill_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM skill_attachments sa
                 USING skill_versions sv
                 WHERE sa.skill_version_id = sv.id
                   AND sa.prompt_version_id = :pv
                   AND sv.skill_id = :sid
                """
            ),
            {"pv": prompt_version_id, "sid": skill_id},
        )


def packs_for_slugs(slugs: list[str]) -> list[SkillPack]:
    """Latest signed DB pack per slug. Disk first-party packs fill gaps so G9 cannot disable a mouth.

    "Gaps" means *no signed version exists* — a first-party bot the tenant has
    never edited. A signed version that exists but will not parse is not a gap,
    and serving the platform default in its place published platform content
    under the tenant's slug: the tool grants the tenant signed away came back,
    with the corrupt row still sitting in the DB unnoticed. Such a slug is
    dropped, so ``intersect.effective_tools`` denies the skill-gated writes
    instead of restoring them.
    """
    if not slugs:
        return []
    from agent_core.skills.pack import pack_for_slug

    packs: list[SkillPack] = []
    with db.engine.connect() as conn:
        for slug in slugs:
            row = _latest_signed_version(conn, slug=slug)
            if row:
                try:
                    packs.append(
                        pack_from_version_row(
                            row,
                            origin=str(row.get("origin") or "first_party"),
                            signed=True,
                        )
                    )
                except Exception:
                    logger.exception("signed skill pack %s failed to parse", slug)
                continue
            try:
                packs.append(pack_for_slug(slug))
            except KeyError:
                continue
    return packs


def sync_attachments_from_card(prompt_version_id: str, card_raw: dict[str, Any] | None) -> None:
    from agent_core.cards.schema import is_authored, parse_card

    if not is_authored(card_raw):
        return
    try:
        card = parse_card(card_raw)
    except Exception:
        return
    slugs = [ref.skill_id for ref in card.skills]
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM skill_attachments WHERE prompt_version_id = :pv"),
            {"pv": prompt_version_id},
        )
        if not slugs:
            return
        for slug in slugs:
            signed = _latest_signed_version(conn, slug=slug)
            if signed is None:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO skill_attachments (prompt_version_id, skill_version_id)
                    VALUES (:pv, :sv) ON CONFLICT DO NOTHING
                    """
                ),
                {"pv": prompt_version_id, "sv": signed["id"]},
            )


def ensure_first_party_skills() -> dict[str, int]:
    """Boot-sync signed first-party packs. Never deletes tenant/gardener drafts.

    Production cannot run seed_postgres.py, so the catalog used to stay empty
    after migrate-only deploys. This is catalog data, not demo customers.
    """
    from agent_core.skills.defaults import CARD_SKILLS, all_first_party_packs

    created = 0
    refreshed = 0
    attached = 0
    cards_filled = 0
    try:
        packs = all_first_party_packs()
    except FileNotFoundError:
        logger.exception("first-party skill packs missing on disk")
        return {"created": 0, "refreshed": 0, "attached": 0, "cardsFilled": 0}

    for pack in packs:
        with db.engine.connect() as conn:
            existing = db._one(
                conn.execute(
                    text(
                        """
                        SELECT id, origin, latest_version_id, signature_status
                          FROM skills
                         WHERE tenant_id = :t AND slug = :s
                        """
                    ),
                    {"t": db._tenant(), "s": pack.slug},
                )
            )
        if existing and existing.get("origin") in {"tenant", "gardener"}:
            continue
        latest_is_this = False
        set_latest = True
        if existing:
            stored = _stored_version(pack.version)
            expected_vid = _version_row_id(existing["id"], stored)
            latest_is_this = existing.get("latest_version_id") in {None, expected_vid}
            set_latest = latest_is_this or existing.get("signature_status") == "signed"
            if existing.get("latest_version_id"):
                refreshed += 1
            else:
                created += 1
        else:
            created += 1
        upsert_skill_from_pack(
            pack,
            origin="first_party",
            signed=True,
            skill_id=existing["id"] if existing else None,
            set_latest=set_latest,
        )

    published = {
        "kaia-v2-4": None,
        "intake-v1": None,
        "insurance-v1": None,
        "supervisor-brief": None,
    }
    with db.engine.connect() as conn:
        for bot_id in list(published):
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT id, agent_card
                          FROM prompt_versions
                         WHERE bot_id = :bot AND status = 'published'
                         LIMIT 1
                        """
                    ),
                    {"bot": bot_id},
                )
            )
            published[bot_id] = row

    skill_version_ids: dict[str, str] = {}
    with db.engine.connect() as conn:
        for slug in {s for slugs in CARD_SKILLS.values() for s in slugs}:
            signed = _latest_signed_version(conn, slug=slug)
            if signed:
                skill_version_ids[slug] = signed["id"]

    with db.engine.begin() as conn:
        for bot_id, slugs in CARD_SKILLS.items():
            row = published.get(bot_id)
            if not row:
                continue
            card = row.get("agent_card") if isinstance(row.get("agent_card"), dict) else {}
            skills = card.get("skills") if isinstance(card.get("skills"), list) else []
            if not skills:
                card = {
                    **card,
                    "skills": [
                        {"skill_id": slug, "version": "1", "pin": "exact"} for slug in slugs
                    ],
                }
                conn.execute(
                    text(
                        """
                        UPDATE prompt_versions
                           SET agent_card = CAST(:card AS jsonb), updated_at = now()
                         WHERE id = :id
                        """
                    ),
                    {"card": db._jsonb(card), "id": row["id"]},
                )
                cards_filled += 1
                skills = card["skills"]
            want = {
                str(s.get("skill_id"))
                for s in skills
                if isinstance(s, dict) and s.get("skill_id")
            } or set(slugs)
            for slug in want:
                vid = skill_version_ids.get(slug)
                if not vid:
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO skill_attachments (prompt_version_id, skill_version_id)
                        VALUES (:pv, :sv) ON CONFLICT DO NOTHING
                        """
                    ),
                    {"pv": row["id"], "sv": vid},
                )
                attached += 1

    logger.info(
        "first-party skills synced created=%s refreshed=%s attached=%s cards_filled=%s",
        created,
        refreshed,
        attached,
        cards_filled,
    )
    return {
        "created": created,
        "refreshed": refreshed,
        "attached": attached,
        "cardsFilled": cards_filled,
    }
