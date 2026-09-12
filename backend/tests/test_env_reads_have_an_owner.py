"""Raw environment reads outside the config owners may only fall.

``os.getenv`` / ``os.environ`` scattered through 67 production modules is a
configuration surface nobody can list: a variable read in one file is
documented nowhere, defaulted differently in the next, and reading it again
is the easiest thing to do. The owners are ``env_utils`` (typed readers),
``env_loader``, ``db_core``, ``platform_flags`` and the ``*config*`` modules;
every other read is counted here, per file, and the count for a file may not
rise, nor a new file appear. Reads move behind an owner one file at a time.

Companion to test_one_clock_one_environment (which pins that every variable
read has a line in .env.example).
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    "tests",
    "scripts",
    "alembic",
    ".venv",
    "node_modules",
    "__pycache__",
    "seeds",
}
OWNER_FILES = ("env_utils.py", "env_loader.py", "db_core.py", "platform_flags.py")

#: file -> raw reads on 2026-09-12. A file may shrink or disappear; never grow or join.
BASELINE: dict[str, int] = {
    "actor_context.py": 6,
    "agent_core/a2a.py": 1,
    "agent_core/cards/routing.py": 1,
    "agent_core/carrier_guard.py": 1,
    "agent_core/clock.py": 1,
    "agent_core/deployment.py": 1,
    "agent_core/guardrails.py": 1,
    "agent_core/logging_contract.py": 3,
    "agent_core/mcp_http/auth.py": 1,
    "agent_core/mcp_http/http_app.py": 5,
    "agent_core/prompt.py": 2,
    "agent_core/providers/fish_tts.py": 2,
    "agent_core/providers/openrouter_tts.py": 2,
    "agent_core/providers/pool.py": 3,
    "agent_core/reco/models.py": 3,
    "agent_core/skills/sign.py": 1,
    "agent_core/tools/kb.py": 1,
    "agent_core/tools/kb_plan.py": 2,
    "agent_core/tools/kb_rerank.py": 3,
    "agent_core/treatment/allocate.py": 2,
    "agent_core/treatment/enact.py": 1,
    "agent_core/treatment/evaluation_seal.py": 1,
    "agent_core/treatment/kill_switch.py": 1,
    "agent_core/treatment/models.py": 2,
    "agent_core/treatment/sweep.py": 1,
    "agent_core/turn_critic.py": 1,
    "agent_core/understanding.py": 2,
    "agent_core/vault/persist.py": 3,
    "agent_core/vault/seal.py": 1,
    "authz.py": 1,
    "azure_openai.py": 8,
    "azure_speech.py": 6,
    "bot_jobs.py": 2,
    "bot_runtime.py": 1,
    "bot_worker.py": 1,
    "db_prompt_studio/deployments.py": 1,
    "kb_ingest.py": 2,
    "kb_rate_limit.py": 1,
    "kb_retrieve.py": 4,
    "llm_gateway/client.py": 8,
    "main.py": 4,
    "mcp_server.py": 3,
    "mcp_tools.py": 1,
    "observability.py": 6,
    "ops_screens.py": 4,
    "outbound.py": 1,
    "provider_voice_sync.py": 1,
    "routers/integrations.py": 4,
    "routers/outbound.py": 4,
    "routers/telephony.py": 3,
    "sandbox_runtime.py": 3,
    "storage.py": 7,
    "tts_catalog_sync.py": 5,
    "tts_preview_cache.py": 2,
    "usage_meter.py": 3,
    "voice/bot_pipeline.py": 1,
    "voice/llm_pool.py": 2,
    "voice/log_bridge.py": 1,
    "voice/tuning_apply.py": 2,
    "voice/ws_proxy.py": 2,
    "voice_sandbox.py": 2,
    "voice_session_store.py": 1,
    "webhooks_dispatch.py": 1,
    "whatsapp.py": 1,
    "whatsapp_outbound.py": 2,
    "wk_batch.py": 1,
}


def _is_env_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if (
            node.func.attr == "getenv"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            return True
        if (
            node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
        ):
            return True
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "environ"
    ):
        return True
    return False


def _raw_reads() -> dict[str, int]:
    out: dict[str, int] = {}
    from tests.source_tree import production_modules

    for path in production_modules(prune=SKIP_DIRS):
        rel = path.relative_to(BACKEND)
        if rel.name.startswith("seed_"):
            continue
        if rel.name in OWNER_FILES or "config" in rel.name:
            continue
        count = sum(
            1 for node in ast.walk(ast.parse(path.read_bytes())) if _is_env_read(node)
        )
        if count:
            out[rel.as_posix()] = count
    return out


def test_raw_env_reads_do_not_grow() -> None:
    reads = _raw_reads()
    joined = sorted(set(reads) - set(BASELINE))
    assert (
        joined == []
    ), f"files that read the environment directly and are not baselined: {joined}"
    grown = {f: (BASELINE[f], n) for f, n in reads.items() if n > BASELINE[f]}
    assert grown == {}, f"files whose raw env reads grew (baseline, now): {grown}"


def test_the_baseline_is_current() -> None:
    """When reads move behind an owner, lower the number so the ratchet keeps biting."""
    reads = _raw_reads()
    stale = {f: (n, reads.get(f)) for f, n in BASELINE.items() if reads.get(f) != n}
    assert (
        stale == {}
    ), f"BASELINE entries that no longer match (baseline, measured): {stale}"
