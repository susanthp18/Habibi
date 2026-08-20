"""Mesh roles are data. Adding a specialist is a JSON edit, not a Python one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice import mesh


def test_shipped_roles_round_trip() -> None:
    loaded = mesh.load_roles()
    assert set(loaded) == {"intake", "collections", "insurance", "supervisor_brief"}
    assert "create_promise_to_pay" in loaded["collections"].tools
    assert "check_product_eligibility" in loaded["insurance"].tools
    assert loaded["supervisor_brief"].tools == ()
    # The in-process map is the same object importers hold.
    assert set(mesh.ROLES) == set(loaded)


def test_unknown_role_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_MULTI_AGENT_ENABLED", "true")
    with pytest.raises(ValueError, match="unknown_mesh_role"):
        mesh.activate_role("legal")


def test_reload_from_temp_file(tmp_path: Path) -> None:
    pack = tmp_path / "roles.json"
    pack.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "roles": [
                    {
                        "name": "collections",
                        "description": "test",
                        "tools": ["verify_identity"],
                    },
                    {
                        "name": "hardship",
                        "description": "intake",
                        "tools": ["flag_dispute"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        mesh.reload_roles(pack)
        assert "hardship" in mesh.ROLES
        assert mesh.ROLES["collections"].tools == ("verify_identity",)
    finally:
        mesh.reload_roles()


def test_malformed_pack_raises(tmp_path: Path) -> None:
    pack = tmp_path / "bad.json"
    pack.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="mesh_roles_empty"):
        mesh.load_roles(pack)
