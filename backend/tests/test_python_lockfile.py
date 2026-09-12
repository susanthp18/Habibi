"""The backend runtime is a 3.12 linux resolve with hashes.

114 of 134 installed packages were constrained nowhere, including the
TLS surface, and the pins were taken from a 3.14 venv while the image
and CI run 3.12. Environment markers therefore resolved differently
(numpy floors, audioop-lts). requires-python makes that mismatch fail
at venv creation; the lockfiles record what actually ships.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

BACKEND = Path(__file__).resolve().parents[1]

REQUIRES_PYTHON = ">=3.12,<3.13"
# Named in the finding as unconstrained on every image build.
TLS_SURFACE = (
    "aiohttp",
    "certifi",
    "cryptography",
    "pyopenssl",
    "requests",
    "urllib3",
)


def _direct_requirements(path: Path) -> dict[str, Requirement]:
    found: dict[str, Requirement] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        key = canonicalize_name(req.name)
        assert key not in found, f"duplicate {req.name} in {path.name}"
        found[key] = req
    return found


def _locked(path: Path) -> dict[str, tuple[Requirement, bool]]:
    """name -> (pinned requirement, has_hash). Continuations joined."""
    found: dict[str, tuple[Requirement, bool]] = {}
    buf = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.split("#", 1)[0].rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        line = (buf + stripped).strip()
        buf = ""
        if not line or line.startswith("--"):
            continue
        req_s, hash_sep, _ = line.partition("--hash=")
        req_s = req_s.strip()
        if not req_s:
            continue
        req = Requirement(req_s)
        found[canonicalize_name(req.name)] = (req, bool(hash_sep))
    return found


def test_requires_python_is_exactly_the_image_interpreter() -> None:
    data = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == REQUIRES_PYTHON
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.12\b", dockerfile, re.M)


def test_lockfiles_are_a_hashed_312_linux_resolve() -> None:
    for name in ("requirements.lock", "requirements-voice.lock"):
        text = (BACKEND / name).read_text(encoding="utf-8")
        assert "--python-version 3.12" in text.splitlines()[1]
        assert "x86_64-unknown-linux-gnu" in text.splitlines()[1]
        assert "--generate-hashes" in text.splitlines()[1]
        locked = _locked(BACKEND / name)
        assert locked, f"{name} is empty"
        unhashed = sorted(n for n, (_, hashed) in locked.items() if not hashed)
        assert not unhashed, f"{name} missing hashes: {unhashed}"
        unpinned = sorted(
            n for n, (req, _) in locked.items() if not req.specifier or "*" in str(req.specifier)
        )
        assert not unpinned, f"{name} has floating pins: {unpinned}"
        assert "audioop-lts" not in locked, (
            f"{name} contains audioop-lts, which pipecat only requires "
            "on python_version >= 3.13 — this is not a 3.12 resolve"
        )


def test_every_declared_requirement_is_locked() -> None:
    api = _locked(BACKEND / "requirements.lock")
    voice = _locked(BACKEND / "requirements-voice.lock")
    for manifest, lock in (
        (BACKEND / "requirements.txt", api),
        (BACKEND / "requirements-voice.txt", voice),
    ):
        for name, req in _direct_requirements(manifest).items():
            assert name in lock, f"{req.name} from {manifest.name} is missing from the lockfile"
            locked_req, _ = lock[name]
            locked_version = Version(next(iter(locked_req.specifier)).version)
            assert locked_version in req.specifier, (
                f"{req.name} locked at {locked_version} does not satisfy "
                f"{req.specifier} in {manifest.name}"
            )


def test_tls_surface_is_hashed_in_the_shipped_tree() -> None:
    combined = {**_locked(BACKEND / "requirements.lock"), **_locked(BACKEND / "requirements-voice.lock")}
    missing = [n for n in TLS_SURFACE if n not in combined]
    assert not missing, f"TLS surface unpinned: {missing}"
    unhashed = [n for n in TLS_SURFACE if not combined[n][1]]
    assert not unhashed, f"TLS surface present without hashes: {unhashed}"


def test_dockerfile_installs_the_lockfiles_with_hashes() -> None:
    src = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    # The voice-dev stage is the laptop test image (pytest, ruff); it ships
    # nowhere, so its unpinned tooling install is not held to the lockfile rule.
    shipped = src.split("FROM voice AS voice-dev", 1)[0]
    installs = [line for line in shipped.splitlines() if "pip install" in line]
    base_install = [line for line in installs if "requirements-voice" not in line]
    assert base_install, "base stage must pip install"
    for line in base_install:
        assert "--require-hashes" in line, line
        assert "requirements.lock" in line, line
    voice_install = [line for line in installs if "requirements-voice" in line]
    assert voice_install, "voice layer must pip install the voice lockfile"
    for line in voice_install:
        assert "--require-hashes" in line, line
        assert "requirements-voice.lock" in line, line
        assert re.search(r"(^|\s)-c\s+requirements\.txt(\s|$)", line), line
