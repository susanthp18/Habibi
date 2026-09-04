"""nltk 3.10.0 and aiohttp 3.14.2 cannot resolve on the voice image.

Pipecat-ai 1.6.0 requires nltk<4,>=3.10.0 as a core dependency and calls
nltk.download("punkt_tab") at import in pipecat.utils.string. 3.10.0
carries 21 advisories closed in 3.10.3. aiohttp 3.14.2 has
GHSA-cq5v-8q36-5273. Neither floor was declared, so an image rebuild
could still land on the vulnerable releases.

This file pins the declared floors and that the voice Dockerfile bakes
punkt_tab under NLTK_DATA outside /app, so process start does not
download.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

BACKEND = Path(__file__).resolve().parents[1]


def _requirements(path: Path) -> dict[str, Requirement]:
    found: dict[str, Requirement] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        assert req.name not in found, f"duplicate {req.name} in {path.name}"
        found[req.name] = req
    return found


def test_voice_requirements_refuse_vulnerable_nltk() -> None:
    spec = _requirements(BACKEND / "requirements-voice.txt")["nltk"].specifier
    assert Version("3.10.3") in spec
    assert Version("3.10.0") not in spec
    assert Version("3.9.0") not in spec
    assert Version("4.0.0") not in spec


def test_voice_requirements_refuse_vulnerable_aiohttp() -> None:
    spec = _requirements(BACKEND / "requirements-voice.txt")["aiohttp"].specifier
    assert Version("3.14.3") in spec
    assert Version("3.14.2") not in spec


def test_api_requirements_refuse_vulnerable_aiohttp() -> None:
    spec = _requirements(BACKEND / "requirements.txt")["aiohttp"].specifier
    assert Version("3.14.3") in spec
    assert Version("3.14.2") not in spec


def test_voice_dockerfile_prebakes_punkt_tab_outside_app() -> None:
    src = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM base AS voice" in src
    voice = src.split("FROM base AS voice", 1)[1]
    match = re.search(r"\bNLTK_DATA=(\S+)", voice)
    assert match, "voice stage must set NLTK_DATA"
    data_dir = match.group(1).strip().strip("\"'")
    assert data_dir.startswith("/"), data_dir
    assert not data_dir.startswith("/app"), (
        "NLTK_DATA under /app is hidden by docker-compose.dev.yml's bind-mount"
    )
    install_at = voice.find("pip install -r requirements-voice.txt")
    assert install_at != -1
    after_install = voice[install_at:]
    assert "punkt_tab" in after_install
    assert "nltk.download" in after_install or "nltk.downloader" in after_install
