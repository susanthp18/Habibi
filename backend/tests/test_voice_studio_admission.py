"""Engine-started dials go through PayInt's contact policy (voice_studio.admit_engine_call)."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import voice_studio


@pytest.fixture
def world(monkeypatch):
    calls: dict = {"admit": [], "activity": []}

    @contextmanager
    def begin():
        yield object()

    monkeypatch.setattr("db.engine", SimpleNamespace(begin=begin))
    monkeypatch.setattr("db._activity", lambda conn, *a, **k: calls["activity"].append(a))
    monkeypatch.setattr("db_whatsapp._find_customer_by_phone",
                        lambda conn, digits: {"id": "C1"} if digits.endswith("9800000001") else None)

    def admit(conn, **kw):
        calls["admit"].append(kw)
        return SimpleNamespace(allowed=False, reason="dnd")

    monkeypatch.setattr("contact_policy.admit", admit)
    monkeypatch.setenv("VOICE_STUDIO_TEST_NUMBERS", "+91 98000 00009")
    return calls


def test_a_customer_is_admitted_by_the_contact_policy(world) -> None:
    out = voice_studio.admit_engine_call({"to_number": "+919800000001", "workflow_run_id": 5})
    assert out == {"admitted": False, "reason": "dnd", "customerId": "C1"}
    assert world["admit"][0]["channel"] == "voice" and world["admit"][0]["customer_id"] == "C1"


def test_strangers_are_refused_and_testers_allowed(world) -> None:
    assert voice_studio.admit_engine_call({"to_number": "+919811111111"})["admitted"] is False
    assert voice_studio.admit_engine_call({"to_number": "9800000009"})["reason"] == "test_number"
    assert not world["admit"]  # neither went to the ledger


def test_payint_dialled_calls_pass_without_a_second_admission(world) -> None:
    assert voice_studio.admit_engine_call({"attempt_id": "AT-1", "to_number": "x"})["admitted"] is True
    assert not world["admit"]
