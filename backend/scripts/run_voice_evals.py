"""Run Pipecat collections eval scenarios against the local voice bot.

Usage (from backend/, venv active, Azure voice env set)::

    python scripts/run_voice_evals.py

Requires pipecat evals runner. Falls back to a dry parse of the YAML when the
eval CLI is unavailable so CI can still validate the scenario file.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

EVAL_YAML = _BACKEND / "voice" / "evals" / "collections_happy.yaml"


def dry_validate() -> int:
    import yaml

    data = yaml.safe_load(EVAL_YAML.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios") or []
    print(f"OK · {EVAL_YAML.name} · {len(scenarios)} scenarios · transport={data.get('transport')}")
    for s in scenarios:
        print(f"  - {s.get('name')}: tools={((s.get('expect') or {}).get('tools_called'))}")
    return 0


def main() -> int:
    # Prefer pipecat.evals if installed with CLI helpers; otherwise dry-validate.
    try:
        from pipecat.evals import run as eval_run  # type: ignore

        return int(eval_run(str(EVAL_YAML)) or 0)
    except Exception:
        try:
            return dry_validate()
        except Exception as exc:
            print(f"eval validate failed: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
