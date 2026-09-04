"""The voice image must not silently override the base pins.

``Dockerfile`` installs ``requirements-voice.txt`` on top of the base
layer. Without ``-c requirements.txt``, pipecat's transitive graph can
upgrade httpx, openai, websockets or ruff inside the voice image only,
so the api image and the voice image built from one commit do not share
a library set and nothing records what either got.

The flag is the gate. Adding the ``evals`` extra (which pulls pipecat's
``cli`` extra and ``ruff>=0.12.1``) must fail the build against
``ruff==0.6.9`` rather than upgrade the linter past its pin.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import Requirement

BACKEND = Path(__file__).resolve().parents[1]


def test_base_requirements_are_legal_pip_constraints() -> None:
    """``-c requirements.txt`` is the voice-layer gate; pip 25 rejects extras."""
    for raw in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        assert not req.extras, (
            f"{req.name} declares extras {sorted(req.extras)}; pip -c "
            "rejects them and the voice image would not build"
        )


def test_voice_dockerfile_constrains_the_voice_install() -> None:
    src = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM base AS voice" in src
    voice = src.split("FROM base AS voice", 1)[1]
    install_lines = [
        line
        for line in voice.splitlines()
        if "pip install" in line and "requirements-voice.txt" in line
    ]
    assert install_lines, "voice stage must pip install requirements-voice.txt"
    constraint = re.compile(r"(^|\s)-c\s+requirements\.txt(\s|$)")
    for line in install_lines:
        assert constraint.search(line), (
            "voice pip install must pass -c requirements.txt so pipecat "
            f"cannot move the base pins; got: {line!r}"
        )
