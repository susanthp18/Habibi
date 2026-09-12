"""Every voice eval scenario is on the suite manifest, and the manifest renders.

Fifteen scenario files existed and the manifest ran six; the other nine were
written, reviewed, and never run by anyone. A scenario that should not run
says so in suite.yaml with the reason; one that is simply missing fails here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
EVALS = BACKEND / "voice" / "evals"


def _manifest_scenarios() -> list[str]:
    data = yaml.safe_load((EVALS / "suite.yaml").read_bytes())
    return [name for entry in data["suite"] for name in entry["scenarios"]]


def test_every_scenario_file_is_on_the_manifest() -> None:
    files = sorted(p.stem for p in (EVALS / "scenarios").glob("*.yaml"))
    listed = _manifest_scenarios()
    assert sorted(listed) == files, {
        "not on the manifest": sorted(set(files) - set(listed)),
        "listed but no file": sorted(set(listed) - set(files)),
    }
    assert len(listed) == len(set(listed)), "a scenario is listed twice"


def test_the_rendered_suite_validates() -> None:
    sys.path.insert(0, str(BACKEND / "scripts"))
    import run_voice_evals

    assert run_voice_evals.main.__module__ == "run_voice_evals"
    sys.argv = ["run_voice_evals.py", "--validate"]
    assert run_voice_evals.main() == 0
