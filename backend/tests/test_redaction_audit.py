"""Every change to what a call's evidence contains leaves an activity row."""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db


def test_muting_an_audio_segment_leaves_an_activity_row(db_tx) -> None:
    """`patch_audio_segment_mute` wrote the flag and nothing else; its sibling,
    `patch_pii_finding`, records who decided what. Muting audio changes what
    an export of the call contains, so it records the same."""
    seg = db_tx.execute(
        text(
            "SELECT s.redaction_id, s.finding_id FROM redaction_audio_segments s "
            "WHERE s.finding_id IS NOT NULL LIMIT 1"
        )
    ).mappings().first()
    if seg is None:
        pytest.skip("seed has no audio segment with a finding")
    before = db_tx.execute(
        text("SELECT count(*) FROM activity_events WHERE entity_id = :r AND kind = 'audio_segment_updated'"),
        {"r": seg["redaction_id"]},
    ).scalar()
    out = db.patch_audio_segment_mute(seg["redaction_id"], seg["finding_id"], True)
    assert out["muted"] is True
    row = db_tx.execute(
        text(
            "SELECT label, note FROM activity_events WHERE entity_type = 'redaction_record' "
            "AND entity_id = :r AND kind = 'audio_segment_updated' ORDER BY at DESC LIMIT 1"
        ),
        {"r": seg["redaction_id"]},
    ).mappings().first()
    assert row is not None
    assert row["label"] == "Audio segment muted"
    assert row["note"] == f"{seg['finding_id']}:muted=True"
    after = db_tx.execute(
        text("SELECT count(*) FROM activity_events WHERE entity_id = :r AND kind = 'audio_segment_updated'"),
        {"r": seg["redaction_id"]},
    ).scalar()
    assert after == before + 1


def test_the_audible_toggle_reaches_every_piece_of_a_findings_beep(db_tx) -> None:
    """A widened beep is cut to the speech in its gap, so one finding can own
    several segments. The reviewer decides per finding: every piece follows."""
    seg = db_tx.execute(
        text(
            "SELECT redaction_id, media_id, finding_id FROM redaction_audio_segments "
            "WHERE finding_id IS NOT NULL LIMIT 1"
        )
    ).mappings().first()
    if seg is None:
        pytest.skip("seed has no audio segment with a finding")
    db_tx.execute(
        text(
            "INSERT INTO redaction_audio_segments (id, redaction_id, media_id, finding_id, at_sec, duration_sec, muted) "
            "VALUES ('RAS-TEST-SECOND-PIECE', :redaction_id, :media_id, :finding_id, 99, 1, true)"
        ),
        dict(seg),
    )
    db.patch_audio_segment_mute(seg["redaction_id"], seg["finding_id"], False)
    muted = db_tx.execute(
        text("SELECT muted FROM redaction_audio_segments WHERE redaction_id = :r AND finding_id = :f"),
        {"r": seg["redaction_id"], "f": seg["finding_id"]},
    ).scalars().all()
    assert len(muted) >= 2 and not any(muted)
