"""Mechanism fixtures cannot train or enact."""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_mechanism_fixture_script_is_simulated_only() -> None:
    src = (BACKEND / "scripts" / "mechanism_fixtures.py").read_text(encoding="utf-8")
    assert "mode='simulated'" in src or "mode = 'simulated'" in src or "'simulated'" in src
    assert "TREATMENT_SIMULATION_OK" in src
    body = src.split("def seed")[1].split("def main")[0]
    assert "recommend_treatment(" not in body


def test_executors_exclude_simulated() -> None:
    claim = (BACKEND / "agent_core" / "treatment" / "decisions.py").read_text(
        encoding="utf-8"
    )
    assert "mode <> 'simulated'" in claim
    follow = (BACKEND / "agent_core" / "treatment" / "followthrough.py").read_text(
        encoding="utf-8"
    )
    assert "mode <> 'simulated'" in follow
