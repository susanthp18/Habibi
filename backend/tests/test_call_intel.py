"""Call intelligence: the invariants the pass must never lose.

No models are loaded here: detection, alignment, the QA tiers and the export
builders are exercised on their own logic with the models' outputs faked.
"""

from __future__ import annotations

import csv
import io

import pytest

from call_intel import audio, pii, qa


def test_spoken_digits_become_a_finding_on_the_original_words() -> None:
    text = "My number is nine eight four five, one two three four five six okay"
    [f] = pii.detect([pii.Turn(0, "customer", text)])
    assert f.type == "phone"
    assert text[f.start:f.end] == "nine eight four five, one two three four five six"


def test_card_needs_luhn_and_aadhaar_needs_verhoeff() -> None:
    found = pii.detect([pii.Turn(0, "customer", "card 4111 1111 1111 1112 and aadhaar 234123412345")])
    assert not any(f.type in ("card", "aadhaar") for f in found)


def test_whatever_follows_a_secret_question_is_a_secret() -> None:
    found = pii.detect([
        pii.Turn(0, "bot", "Please tell me the OTP you received."),
        pii.Turn(1, "customer", "It is four two nine one."),
        pii.Turn(2, "customer", "I can pay four thousand."),
    ])
    assert [(f.turn_index, f.type) for f in found] == [(1, "secret")]


def test_customers_own_record_is_matched_and_the_persona_is_not() -> None:
    found = pii.detect(
        [pii.Turn(0, "bot", "Hi, I'm Kaia. Is this Anita Desai?")],
        crm={"name": ["Anita Desai"]},
        model_spans={0: [(8, 12, "name", 0.8)]},  # the model flags "Kaia"
        allow_names=["Kaia"],
    )
    assert [(f.type, f.detector) for f in found] == [("name", "crm")]


def test_an_unaligned_word_widens_the_beep_and_never_moves_it() -> None:
    turn = pii.Turn(0, "customer", "card 4111 1111 1111 1111 thanks")
    heard = [audio._Token("card", 1.0, 1.2), *[audio._Token(d, 1.3 + 0.1 * i, 1.4 + 0.1 * i)
                                                for i, d in enumerate("4111")],
             audio._Token("thanks", 5.0, 5.3)]
    [seg] = audio.time_findings(pii.detect([turn]), [turn], "customer", heard, 10.0)
    assert seg.source == "utterance_fallback"
    assert seg.start_ms <= 1300 and seg.end_ms >= 5000  # covers every digit, heard or not


def test_exports_never_ship_the_original_recording(monkeypatch) -> None:
    from call_intel import exports

    monkeypatch.setattr("voice.recordings.media_for_interaction",
                        lambda ix, variant="original": None if variant == "redacted" else {"storage_ref": "x"})
    with pytest.raises(exports.NotReady):
        exports._redacted_audio("CL-1")


def test_csv_export_carries_the_watermark_on_every_row() -> None:
    from call_intel import exports

    rec = {"interaction_id": "CL-1", "redaction_id": "RR-1", "customer_id": "C1", "channel": "voice",
           "direction": "outbound", "started_at": None, "ended_at": None, "duration_sec": 60, "agent": "Kaia",
           "studio": {"versionNumber": 3}, "disposition": "ptp", "reviewed": True, "reviewer": "Priya",
           "reviewed_at": None, "masked_by_type": {"name": 2}, "log_hash": ""}
    rows = list(csv.DictReader(io.StringIO(
        exports.build_csv({"id": "EX-1", "watermark": "RBI audit"}, [rec]).decode("utf-8-sig"))))
    assert rows[0]["watermark"] == "RBI audit" and rows[0]["agentVersion"] == "3"


def test_tier1_settles_only_when_there_was_nothing_to_judge() -> None:
    calm = {"intents": {}, "sentiment": [(1, 0.4)]}
    upset = {"intents": {"hardship": [3]}, "sentiment": [(1, 0.1), (3, -0.6)]}
    facts = {"flags": [], "upsell_presented": False, "handoff": False, "opted_out": False}
    assert qa.tier1("emp-acknowledge", calm, facts)[0] == qa.NEUTRAL
    assert qa.tier1("emp-acknowledge", upset, facts) is None  # the judge reads it
    assert qa.tier1("res-answer", calm, facts) is None


def test_detectors_hold_the_eval_gate_without_the_model() -> None:
    """The identifiers must never depend on the model: with it down, structured
    recall and precision still hold (call_intel.eval; names/addresses in prose
    are the model's and are measured with it in the ml image)."""
    from call_intel import eval as pii_eval

    report = pii_eval.run(use_model=False)
    assert report["structuredRecall"] >= pii_eval.GATE["structured"], report["notes"]
    assert report["precision"] >= pii_eval.GATE["precision"], report["notes"]


def test_reconcile_resolves_the_agent_of_calls_filed_without_one(monkeypatch) -> None:
    """Early calls were filed as plain "voice-studio"; the repair built
    /workflow/voice-studio/runs/7 and the engine answered 422 on every sweep.
    The agent now comes from the bot id, else the engine's own run listing
    (fetched once, a year back)."""
    import voice_studio

    fetched: list[str] = []

    def listing(since: str, until: str) -> list[dict]:
        fetched.append(since)
        return [{"id": 7, "workflow_id": 3}, {"id": 8, "workflow_id": 3}]

    monkeypatch.setattr(voice_studio, "_engine_runs", listing)
    resolve = voice_studio._workflow_resolver([{"id": 42, "workflow_id": 9}], "2026-09-27T00:00:00")
    assert resolve(1, "voice-studio-5") == 5
    assert resolve(42, "voice-studio") == 9 and fetched == []
    assert resolve(7, "voice-studio") == 3 and resolve(8, None) == 3
    assert resolve(99, "voice-studio") is None
    assert len(fetched) == 1
