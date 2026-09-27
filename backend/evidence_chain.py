"""Tamper-evident call evidence: one hash-chain link per filed call.

    link.hash = sha256(prev_hash | interaction_id | transcript_sha256 | recording_sha256)

``transcript_sha256`` covers the words as spoken (the engine's transcript,
speaker and text per turn, before any masking); ``recording_sha256`` is the
filed recording's digest. Changing either, or removing or reordering links,
breaks the chain from that point on. The link's hash is also the call's
``interactions.hash`` (the "Log hash" in Audit).

Limit, stated: an attacker who can rewrite the whole table and every later
link can forge a consistent chain. Anchoring the head hash outside the
database (a daily signed export) closes that; ``head()`` is what to anchor.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

GENESIS = "0" * 64


def transcript_digest(turns: list[tuple[str, str]]) -> str:
    """sha256 of the conversation as (speaker, text) pairs, canonical JSON."""
    canonical = json.dumps([[s, t] for s, t in turns], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def link_hash(prev_hash: str, interaction_id: str, transcript_sha: str, recording_sha: str | None) -> str:
    material = "|".join([prev_hash, interaction_id, transcript_sha, recording_sha or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append(interaction_id: str, turns: list[tuple[str, str]], recording_sha: str | None) -> str | None:
    """Add the call's link once; returns its hash (the existing one on a re-file)."""
    import db

    tenant = db.current_tenant()
    with db.engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"evidence-chain:{tenant}"})
        existing = conn.execute(
            text("SELECT hash FROM interaction_evidence_chain WHERE interaction_id = :ix"), {"ix": interaction_id}
        ).scalar()
        if existing:
            return str(existing)
        prev = conn.execute(
            text("SELECT hash FROM interaction_evidence_chain WHERE tenant_id = :t ORDER BY seq DESC LIMIT 1"),
            {"t": tenant},
        ).scalar() or GENESIS
        t_sha = transcript_digest(turns)
        h = link_hash(prev, interaction_id, t_sha, recording_sha)
        conn.execute(
            text("INSERT INTO interaction_evidence_chain (tenant_id, interaction_id, transcript_sha256, "
                 "recording_sha256, prev_hash, hash) VALUES (:t, :ix, :ts, :rs, :p, :h)"),
            {"t": tenant, "ix": interaction_id, "ts": t_sha, "rs": recording_sha, "p": prev, "h": h},
        )
        conn.execute(text("UPDATE interactions SET hash = :h WHERE id = :ix"), {"h": h, "ix": interaction_id})
    return h


def verify(interaction_id: str, *, turns: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Recompute one call's link: its hash from its parts and predecessor, the
    predecessor's existence, the recording's bytes, and (when the words can be
    re-read) the transcript. Every check is reported, not just the first."""
    import db
    from voice.recordings import _load_bytes, media_for_interaction

    with db.engine.connect() as conn:
        link = conn.execute(
            text("SELECT seq, tenant_id, transcript_sha256, recording_sha256, prev_hash, hash "
                 "FROM interaction_evidence_chain WHERE interaction_id = :ix"), {"ix": interaction_id}
        ).mappings().first()
        if link is None:
            return {"linked": False, "ok": False, "checks": [{"check": "linked", "ok": False}]}
        prev_row = conn.execute(
            text("SELECT hash FROM interaction_evidence_chain WHERE tenant_id = :t AND seq < :s "
                 "ORDER BY seq DESC LIMIT 1"), {"t": link["tenant_id"], "s": link["seq"]}
        ).scalar()
    checks = [
        {"check": "link", "ok": link_hash(link["prev_hash"], interaction_id, link["transcript_sha256"],
                                          link["recording_sha256"]) == link["hash"]},
        {"check": "predecessor", "ok": (prev_row or GENESIS) == link["prev_hash"]},
    ]
    media = media_for_interaction(interaction_id, variant="original")
    if link["recording_sha256"]:
        actual = hashlib.sha256(_load_bytes(str(media["storage_ref"]))).hexdigest() if media else None
        checks.append({"check": "recording", "ok": actual == link["recording_sha256"]})
    if turns is not None:
        checks.append({"check": "transcript", "ok": transcript_digest(turns) == link["transcript_sha256"]})
    return {"linked": True, "ok": all(c["ok"] for c in checks), "hash": link["hash"], "seq": link["seq"],
            "checks": checks}


def head(tenant_id: str | None = None) -> dict[str, Any] | None:
    """The chain's latest link: the value to anchor outside the database."""
    import db

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT seq, hash, created_at FROM interaction_evidence_chain WHERE tenant_id = :t "
                 "ORDER BY seq DESC LIMIT 1"), {"t": tenant_id or db.current_tenant()}
        ).mappings().first()
    return dict(row) if row else None


if __name__ == "__main__":
    a = link_hash(GENESIS, "CL-1", transcript_digest([("bot", "hi")]), "r1")
    assert a == link_hash(GENESIS, "CL-1", transcript_digest([("bot", "hi")]), "r1")
    assert a != link_hash(GENESIS, "CL-1", transcript_digest([("bot", "hi!")]), "r1")
    assert a != link_hash(a, "CL-1", transcript_digest([("bot", "hi")]), "r1")
    print("ok")
