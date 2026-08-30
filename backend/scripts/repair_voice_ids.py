#!/usr/bin/env python
"""Repair one corrupted draft's voice, and report every other id that cannot speak.

    .venv/Scripts/python scripts/repair_voice_ids.py            # report only
    .venv/Scripts/python scripts/repair_voice_ids.py --apply    # repair the draft

Written for a specific row and left in the repo because the class of damage
outlives it. Draft ``v1_5-aace95`` on ``kaia-v2-4`` — a live demo card whose
persona is English / en-IN and whose published v1.4 speaks ``en-IN-AartiNeural``
— was carrying ``fish:7e4fa512aa564e198f8659b466f6ff70``: AboFlah, an Arabic
Fish voice. Nothing in the product said so. The Voice tab rendered it as
Selected (correctly — it *is* what the draft stores), the compiler passed every
gate, and Publish was enabled. One click would have shipped an English
collections bot speaking Arabic.

G15 ``voice_locale`` now warns on exactly that shape, so the silence is fixed
going forward. This script fixes the row that was written during the silence.

Only ``voice.voiceId`` and ``voice.azureVoiceName`` are rewritten. The draft
predates today and may hold intentional work, so every other key on the voice
object and every other column on the row is left exactly as found.

The scan is deliberately read-only. Legacy aliases like v1.2's ``ravi`` are not
catalog short names and never were — they resolve through
``azure_speech._voice_map()``, and ``resolve_prompt_azure_voice`` prefers the
row's own ``azureVoiceName`` anyway, so most of them speak correctly. Reporting
them is useful; rewriting them would be a migration, and one that touched
archived history at that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

import db  # noqa: E402

#: The row this script was written for, and the voice its card actually speaks.
TARGET_VERSION_ID = "v1_5-aace95"
TARGET_VOICE = "en-IN-AartiNeural"


def _voice_of(conn, version_id: str) -> dict | None:
    raw = db._one(
        conn.execute(
            text("SELECT voice::text AS voice FROM prompt_versions WHERE id = :id"),
            {"id": version_id},
        )
    )
    return json.loads(raw["voice"]) if raw else None


def repair(apply: bool) -> int:
    with db.engine.connect() as conn:
        before = _voice_of(conn, TARGET_VERSION_ID)
    if before is None:
        print(f"{TARGET_VERSION_ID}: no such prompt version — nothing to repair")
        return 0

    print(f"{TARGET_VERSION_ID} before: {json.dumps(before, ensure_ascii=False)}")
    if before.get("voiceId") == TARGET_VOICE and before.get("azureVoiceName") == TARGET_VOICE:
        print(f"{TARGET_VERSION_ID}: already {TARGET_VOICE} — nothing to do")
        return 0
    if not apply:
        print(f"{TARGET_VERSION_ID}: would set voiceId/azureVoiceName -> {TARGET_VOICE} (--apply)")
        return 0

    # jsonb_set twice rather than writing a whole object: the two keys named
    # here are the only ones that may change, and a full rewrite would silently
    # reorder or drop anything this script did not think to carry.
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE prompt_versions
                SET voice = jsonb_set(
                      jsonb_set(voice, '{voiceId}', to_jsonb(CAST(:v AS text)), true),
                      '{azureVoiceName}', to_jsonb(CAST(:v AS text)), true
                    ),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": TARGET_VERSION_ID, "v": TARGET_VOICE},
        )
    with db.engine.connect() as conn:
        after = _voice_of(conn, TARGET_VERSION_ID)
    print(f"{TARGET_VERSION_ID} after:  {json.dumps(after, ensure_ascii=False)}")

    changed = sorted(k for k in set(before) | set(after or {}) if before.get(k) != (after or {}).get(k))
    print(f"{TARGET_VERSION_ID} changed keys: {changed}")
    return 0


def scan() -> None:
    """Every stored voice whose id the catalog cannot resolve. Report only."""
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, bot_id, label, status,
                           voice ->> 'voiceId' AS voice_id,
                           voice ->> 'azureVoiceName' AS azure_name
                    FROM prompt_versions
                    ORDER BY bot_id, created_at
                    """
                )
            )
        )

    print("\nunresolvable ids (report only):")
    problems = 0
    for r in rows:
        speaks = db.resolve_prompt_azure_voice(
            {"voiceId": r["voice_id"], "azureVoiceName": r["azure_name"]}
        )
        stored_ok = db.get_tts_voice_catalog_entry(r["voice_id"] or "") is not None
        speaks_ok = db.get_tts_voice_catalog_entry(speaks) is not None
        if stored_ok and speaks_ok:
            continue
        problems += 1
        # "speaks" is the honest column: a legacy voiceId beside a valid
        # azureVoiceName is untidy, not broken, and the two must not read alike.
        print(
            f"  {r['id']:<16} {r['bot_id']:<20} {r['status']:<10} "
            f"voiceId={r['voice_id']!r:<22} speaks={speaks!r}"
            f"{'' if speaks_ok else '  <-- runtime falls back'}"
        )
    if not problems:
        print("  none")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the repair (default: dry run)")
    args = ap.parse_args()
    rc = repair(args.apply)
    scan()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
