"""Pin the safe subset of container hardening (WP-059).

The voice image used to ship ``build-essential`` next to ffmpeg, and
``.dockerignore`` left ``tests/`` in every image. Compose healthchecks
covered redis/db/minio/api and none of the four workers.

This file pins those three. It does not pin a non-root USER, memory or
CPU limits, ``cap_drop`` / ``read_only``, or a split ``env_file`` —
those change the running uid, can OOM the process that terminates
borrower calls, or strip secrets from a worker that still reads them.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

_FROM = re.compile(r"^FROM\s+\S+(?:\s+AS\s+(\S+))?", re.M | re.I)
_SERVICE = re.compile(
    r"^  ([A-Za-z0-9_]+):\n(.*?)(?=^  [A-Za-z0-9_]+:|\Z)",
    re.M | re.S,
)

WORKER_SERVICES = ("worker", "bot_worker", "voice")


def _stages(src: str) -> dict[str, str]:
    matches = list(_FROM.finditer(src))
    out: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group(1) or f"anonymous-{i}"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        out[name] = src[match.end() : end]
    return out


def _services(src: str) -> dict[str, str]:
    return {name: body for name, body in _SERVICE.findall(src)}


def test_dockerignore_excludes_tests() -> None:
    lines = [
        line.strip()
        for line in (BACKEND / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "tests/" in lines, (
        ".dockerignore must exclude tests/ so the 190 test files do not "
        "ship in every image"
    )


def test_voice_stage_does_not_keep_a_c_toolchain() -> None:
    stages = _stages((BACKEND / "Dockerfile").read_text(encoding="utf-8"))
    assert "builder" in stages, "native wheels must compile in a discarded builder stage"
    assert "voice" in stages
    assert re.search(r"\bbuild-essential\b", stages["builder"]), (
        "builder stage must install build-essential to compile wheels"
    )
    assert not re.search(r"\bbuild-essential\b", stages["voice"]), (
        "final voice image must not retain the C toolchain"
    )
    assert re.search(r"\bffmpeg\b", stages["voice"]), (
        "ffmpeg is a runtime dependency of the voice runner"
    )
    assert re.search(r"COPY\s+--from=builder\s+/usr/local\s+/usr/local", stages["voice"])


def test_four_workers_have_healthchecks() -> None:
    services = _services((BACKEND / "docker-compose.yml").read_text(encoding="utf-8"))
    missing = [name for name in WORKER_SERVICES if "healthcheck:" not in services.get(name, "")]
    assert not missing, f"worker services missing a healthcheck: {missing}"
    voice = services["voice"]
    assert "7860" in voice.split("healthcheck:", 1)[1], (
        "voice healthcheck must probe the runner port, not merely PID 1"
    )


def test_every_worker_entrypoint_installs_a_log_handler() -> None:
    """WS7: wk_batch had no log handler, so its INFO lines went nowhere and
    its warnings came out unformatted. Walk the compose services' Python
    entrypoints and hold each to `observability.setup_logging()` or a
    `logging.basicConfig` of its own."""
    import re
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    compose = (backend / "docker-compose.yml").read_text(encoding="utf-8")
    modules = re.findall(r'command: \["python", "-m", "([a-z_.]+)"', compose)
    assert modules, "no python -m entrypoints found in docker-compose.yml"
    for module in modules:
        path = backend / (module.replace(".", "/") + ".py")
        src = path.read_text(encoding="utf-8")
        # The voice bot logs through loguru and voice/log_bridge, which
        # installs its own sink; the others configure the stdlib root.
        assert (
            "setup_logging()" in src
            or "logging.basicConfig(" in src
            or "from voice import log_bridge" in src
        ), f"{module} installs no log handler"


def test_every_bucket_the_platform_writes_is_provisioned(monkeypatch) -> None:
    """WS8: ensure_bucket created the KB bucket alone, so a recording on a
    fresh MinIO fell back into `collections-kb`."""
    import storage

    made: list[str] = []

    class _Client:
        def bucket_exists(self, b):
            return False

        def make_bucket(self, b):
            made.append(b)

    monkeypatch.setattr(storage, "is_configured", lambda: True)
    monkeypatch.setattr(storage, "get_client", lambda: _Client())
    storage.ensure_bucket()
    assert set(made) == {storage.get_bucket(), storage.RECORDINGS_BUCKET}
