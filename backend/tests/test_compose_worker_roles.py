"""One worker role, one compose service, same image (WP-039)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_core.worker_roles import ROLES

BACKEND = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((BACKEND / "docker-compose.yml").read_text(encoding="utf-8"))


def test_every_role_has_a_split_service_on_the_bot_worker_image() -> None:
    services = _compose()["services"]
    base = services["bot_worker"]
    assert "profiles" not in base, "the combined worker is the laptop default"
    for role in ROLES:
        svc = services[f"{role}_worker"]
        assert svc["profiles"] == ["split-workers"], role
        assert svc["image"] == base["image"], role
        assert svc["command"] == base["command"], role
        assert svc["environment"]["BOT_WORKER_ROLE"] == role
        assert svc["environment"]["DB_PROCESS_ROLE"] == "bot_worker"
        assert svc["cap_drop"] == ["ALL"], role


def test_the_roles_partition_the_queues() -> None:
    seen: dict[str, str] = {}
    for role, queues in ROLES.items():
        for q in queues:
            assert q not in seen, f"{q} in both {seen[q]} and {role}"
            seen[q] = role


def test_idle_worker_backs_off() -> None:
    import bot_worker

    assert bot_worker.idle_sleep(0, 1.5) == 1.5
    assert bot_worker.idle_sleep(bot_worker.IDLE_TICKS_BEFORE_BACKOFF - 1, 1.5) == 1.5
    assert bot_worker.idle_sleep(bot_worker.IDLE_TICKS_BEFORE_BACKOFF, 1.5) == 5.0
    assert bot_worker.idle_sleep(10_000, 8.0) == 8.0  # a slower poll is never sped up
