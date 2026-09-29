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


def _heard(*words: tuple[str, float]) -> list:
    return [audio._Token(w, s, s + 0.3) for w, s in words]


def test_a_name_heard_spelled_otherwise_is_beeped_where_it_was_said() -> None:
    """The recogniser wrote the CRM's "Susanth" as "susant". It is still the word
    said there: the beep sits on it instead of widening across the silence to
    the bot's next turn (7 s of tone over the customer's reply, 2026-09-29)."""
    turns = [pii.Turn(0, "bot", "Am I speaking with Susanth?"), pii.Turn(2, "bot", "Thanks for confirming.")]
    heard = _heard(("am", 5.5), ("i", 5.8), ("speaking", 5.9), ("with", 6.4), ("susant", 6.6),
                   ("thanks", 13.4), ("for", 13.8), ("confirming", 14.0))
    [seg] = audio.time_findings(pii.detect(turns, crm={"name": ["Susanth"]}), turns, "agent", heard, 20.0)
    assert seg.source == "aligned"
    assert (seg.start_ms, seg.end_ms) == (6600 - audio.PAD_MS, 6900 + audio.PAD_MS)


def test_an_unheard_digit_widens_over_that_speech_not_to_the_next_turn() -> None:
    """The recogniser dropped the last digit of the answer. The beep covers the
    rest of that answer, and stops there: not 27 s later at the customer's next
    word, over everything the bot said in between."""
    turns = [pii.Turn(0, "bot", "Tell me the last four digits of your mobile."),
             pii.Turn(1, "customer", "I think it is 2324."),
             pii.Turn(3, "customer", "No, actually I want to postpone.")]
    heard = _heard(("i", 25.8), ("think", 26.9), ("it", 27.3), ("is", 27.7), ("2", 28.1), ("3", 28.5),
                   ("2", 28.8), ("no", 54.9), ("actually", 56.0), ("i", 56.4), ("want", 56.6),
                   ("to", 56.8), ("postpone", 57.0))
    speech = [(25.7, 29.5), (54.8, 59.2)]
    [seg] = audio.time_findings(pii.detect(turns), turns[1:], "customer", heard, 151.0, speech)
    assert seg.source == "utterance_fallback"
    assert (seg.start_ms, seg.end_ms) == (28100 - audio.PAD_MS, 29500 + audio.PAD_MS)


def test_a_word_never_heard_is_beeped_wherever_that_speaker_spoke_in_its_gap() -> None:
    """Nothing the recogniser heard lines up with the flagged word: every run of
    that speaker's speech between its neighbours is beeped (fail closed), and
    none of the silence -- a segment per run."""
    turns = [pii.Turn(0, "customer", "Okay."), pii.Turn(2, "customer", "Harry, come again?"),
             pii.Turn(4, "customer", "Yes please.")]
    heard = _heard(("okay", 40.0), ("yes", 83.3), ("please", 83.6))
    speech = [(39.9, 40.3), (47.0, 47.9), (60.8, 61.8), (83.2, 84.0)]
    found = pii.detect(turns, model_spans={2: [(0, 5, "name", 0.72)]})
    segs = audio.time_findings(found, turns, "customer", heard, 127.0, speech)
    assert [(s.start_ms, s.end_ms, s.source) for s in segs] == [
        (47000 - audio.PAD_MS, 47900 + audio.PAD_MS, "utterance_fallback"),
        (60800 - audio.PAD_MS, 61800 + audio.PAD_MS, "utterance_fallback"),
    ]


def test_a_beep_runs_on_to_the_pause_after_its_words() -> None:
    """A word's timestamp can end before the word does (the tail of a digit was
    audible past the beep): the end moves on to the pause, by at most SNAP_MS."""
    turns = [pii.Turn(0, "bot", "Please tell me the OTP."), pii.Turn(1, "customer", "It is 4291.")]
    heard = _heard(("it", 1.0), ("is", 1.3), ("4", 1.6), ("2", 1.9), ("9", 2.2), ("1", 2.5))
    found = pii.detect(turns)
    [near] = audio.time_findings(found, turns[1:], "customer", heard, 10.0, [(0.9, 3.0)])
    assert near.source == "aligned" and near.end_ms == 3000 + audio.PAD_MS
    [far] = audio.time_findings(found, turns[1:], "customer", heard, 10.0, [(0.9, 6.0)])
    assert far.end_ms == 2800 + audio.SNAP_MS + audio.PAD_MS


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
