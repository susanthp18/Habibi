"""Prompt lint disclosure regex — avoid false positives on unrelated 'record' words."""

from __future__ import annotations

from prompt_lint import lint_prompt


def test_recording_disclosure_required_when_missing() -> None:
    findings = lint_prompt(
        "You are a collections agent. Help the customer pay.",
        {"alwaysDiscloseRecording": True},
    )
    codes = {f["code"] for f in findings}
    assert "missing_recording_disclosure" in codes


def test_recording_disclosure_accepts_call_is_recorded() -> None:
    findings = lint_prompt(
        "This call is being recorded for quality. Help with EMI.",
        {"alwaysDiscloseRecording": True},
    )
    codes = {f["code"] for f in findings}
    assert "missing_recording_disclosure" not in codes


def test_recording_disclosure_ignores_unrelated_record() -> None:
    findings = lint_prompt(
        "Update the customer's account record after the payment posts.",
        {"alwaysDiscloseRecording": True},
    )
    codes = {f["code"] for f in findings}
    assert "missing_recording_disclosure" in codes
