"""Run Pipecat collections eval scenarios against the local voice bot.

Usage (from backend/, venv active, Azure voice env set)::

    python scripts/run_voice_evals.py

Requires the pipecat eval CLI. Falls back to a structural validation of the
scenario files when the CLI is unavailable, so CI still catches a malformed
scenario without needing Azure credentials.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

EVAL_DIR = _BACKEND / "voice" / "evals"
SUITE_YAML = EVAL_DIR / "suite.yaml"
SCENARIOS_DIR = EVAL_DIR / "scenarios"

# Days ahead for a scenario's promise-to-pay date. Far enough that the bot's own
# "not in the past" validation never rejects it, near enough to stay a plausible
# collections commitment.
_PROMISE_DAYS_AHEAD = 14

_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()


def _promise_substitutions(today: date | None = None) -> dict[str, str]:
    """Both forms of the promise date, derived from ONE value.

    The scenario's spoken utterance and its expected normalised ``promise_date``
    argument must agree exactly. Hardcoding an absolute date kept them in sync
    but expired; deriving both here keeps them in sync forever.
    """
    when = (today or date.today()) + timedelta(days=_PROMISE_DAYS_AHEAD)
    day = when.day
    suffix = (
        "th"
        if 11 <= day % 100 <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    )
    return {
        "promise_date": when.isoformat(),
        "promise_date_spoken": f"the {day}{suffix} of {_MONTHS[when.month - 1]} {when.year}",
    }


def _render(text_in: str, subs: dict[str, str]) -> str:
    for key, value in subs.items():
        text_in = text_in.replace("{{" + key + "}}", value)
    return text_in


def _render_suite(dest: Path) -> Path:
    """Copy the eval tree into ``dest`` with placeholders substituted.

    Returns the rendered manifest path. ``bot:`` is rewritten to an absolute
    path because Pipecat resolves it against the manifest's own directory, and
    the rendered manifest no longer lives next to voice/bot.py.
    """
    subs = _promise_substitutions()
    (dest / "scenarios").mkdir(parents=True, exist_ok=True)
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        (dest / "scenarios" / path.name).write_text(
            _render(path.read_text(encoding="utf-8"), subs), encoding="utf-8"
        )
    manifest = dest / SUITE_YAML.name
    manifest.write_text(
        _render(SUITE_YAML.read_text(encoding="utf-8"), subs).replace(
            "- bot: ../bot.py", f"- bot: {(_BACKEND / 'voice' / 'bot.py').as_posix()}"
        ),
        encoding="utf-8",
    )
    return manifest

# pipecat.evals.scenario: EvalExpectation fields. Anything else in an `expect`
# entry is silently ignored by the runner, which is how the old `tools_called` /
# `no_phrases` keys sat in the file for weeks asserting nothing at all.
_EXPECTATION_KEYS = {"event", "within_ms", "text_contains", "calls", "eval"}
_TURN_KEYS = {"user", "dtmf", "expect", "send_after", "image"}


def dry_validate(scenarios_dir: Path | None = None) -> int:
    """Structurally validate every scenario file against the Pipecat schema.

    Validates the *rendered* scenarios by default, so CI checks exactly what the
    eval CLI would be handed rather than the un-substituted templates.
    """
    import yaml

    scenarios_dir = scenarios_dir or SCENARIOS_DIR
    files = sorted(scenarios_dir.glob("*.yaml"))
    if not files:
        print(f"no scenario files in {scenarios_dir}", file=sys.stderr)
        return 1

    errors: list[str] = []
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            # A list/scalar root would make every .get() below raise, turning a
            # malformed scenario into a crash instead of a FAIL line.
            errors.append(f"{path.name}: root must be a mapping, got {type(data).__name__}")
            continue
        if not data.get("name"):
            errors.append(f"{path.name}: missing top-level `name`")
        turns = data.get("turns")
        if not isinstance(turns, list) or not turns:
            errors.append(f"{path.name}: `turns` must be a non-empty list")
            continue
        for i, turn in enumerate(turns):
            if not isinstance(turn, dict):
                errors.append(f"{path.name}: turn {i} is not a mapping")
                continue
            unknown = set(turn) - _TURN_KEYS
            if unknown:
                errors.append(f"{path.name}: turn {i} has unknown keys {sorted(unknown)}")
            if turn.get("user") and turn.get("dtmf"):
                errors.append(f"{path.name}: turn {i} sets both `user` and `dtmf`")
            expectations = turn.get("expect") or []
            if not isinstance(expectations, list):
                errors.append(f"{path.name}: turn {i} `expect` must be a list")
                continue
            for j, exp in enumerate(expectations):
                if not isinstance(exp, dict):
                    errors.append(f"{path.name}: turn {i} expect {j} is not a mapping")
                    continue
                if not exp.get("event"):
                    errors.append(f"{path.name}: turn {i} expect {j} missing `event`")
                unknown = set(exp) - _EXPECTATION_KEYS
                if unknown:
                    errors.append(
                        f"{path.name}: turn {i} expect {j} has unsupported keys "
                        f"{sorted(unknown)} — the runner ignores these"
                    )
                calls = exp.get("calls")
                if calls is not None:
                    if exp.get("event") != "function_call":
                        errors.append(
                            f"{path.name}: turn {i} expect {j} sets `calls` on "
                            f"event={exp.get('event')!r}"
                        )
                    if not isinstance(calls, list):
                        errors.append(
                            f"{path.name}: turn {i} expect {j} `calls` must be a list, "
                            f"got {type(calls).__name__}"
                        )
                        continue
                    for call in calls or []:
                        if not isinstance(call, dict) or not call.get("name"):
                            errors.append(
                                f"{path.name}: turn {i} expect {j} has a call without `name`"
                            )

    if errors:
        for e in errors:
            print(f"FAIL · {e}", file=sys.stderr)
        return 1

    print(f"OK · {len(files)} scenarios validated in {scenarios_dir}")
    for path in files:
        print(f"  - {path.stem}")
    return 0


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="voice-evals-"))
    try:
        manifest = _render_suite(work)
        rendered_scenarios = work / "scenarios"
        # Prefer the real eval CLI; fall back to structural validation.
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pipecat.cli", "eval", "run", str(manifest), "-v"],
                cwd=str(_BACKEND),
                check=False,
            )
        except (OSError, ValueError) as exc:
            print(f"pipecat eval CLI unavailable ({exc}); validating scenarios only")
            return dry_validate(rendered_scenarios)
        if proc.returncode == 0:
            return 0
        # Distinguish "CLI missing" from "evals failed": only fall back on the
        # former, otherwise a real eval failure would be reported as success.
        if proc.returncode in (1, 2) and not _cli_available():
            return dry_validate(rendered_scenarios)
        return proc.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _cli_available() -> bool:
    """True only if `python -m pipecat.cli` is actually runnable.

    Checking `import pipecat.cli` was wrong: the package imports fine but has no
    __main__, so `-m` exits non-zero and the runner reported a *tooling* gap as
    an eval failure instead of falling back to structural validation.
    """
    from importlib.util import find_spec

    try:
        return find_spec("pipecat.cli.__main__") is not None
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
