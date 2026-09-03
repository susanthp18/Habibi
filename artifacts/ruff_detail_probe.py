"""Extract noqa-hidden and wider-rule details as plain UTF-8."""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

BACKEND = Path(r"D:\Hackathon\backend")
OUT = Path(r"D:\Hackathon\artifacts")
RUFF = BACKEND / ".venv" / "Scripts" / "ruff.exe"


def run(args: list[str]) -> tuple[int, str]:
    import os

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    proc = subprocess.run(
        [str(RUFF), *args],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def main() -> None:
    jobs = [
        (["check", ".", "--select", "E402", "--ignore-noqa", "--output-format=concise"], "detail-e402-noqa.txt"),
        (["check", ".", "--select", "F401,F841,F811", "--ignore-noqa", "--output-format=concise"], "detail-f-noqa.txt"),
        (["check", ".", "--select", "E,F,W,I,UP,B,SIM", "--statistics"], "wider-stats.txt"),
        (["check", ".", "--select", "E,F,W,I,UP,B,SIM", "--output-format=concise"], "wider-concise.txt"),
        # Isolated = ignore project per-file-ignores; reveals load-bearing E402 volume
        (
            [
                "check",
                "voice/bot.py",
                "worker.py",
                "bot_worker.py",
                "voice/spike.py",
                "--isolated",
                "--select",
                "E402",
                "--target-version",
                "py312",
                "--output-format=concise",
            ],
            "isolated-e402-entrypoints.txt",
        ),
        (
            [
                "check",
                "scripts",
                "--isolated",
                "--select",
                "E402",
                "--target-version",
                "py312",
                "--statistics",
            ],
            "isolated-e402-scripts-stats.txt",
        ),
        (
            [
                "check",
                ".",
                "--isolated",
                "--select",
                "E402",
                "--target-version",
                "py312",
                "--statistics",
            ],
            "isolated-e402-all-stats.txt",
        ),
        (
            [
                "check",
                ".",
                "--isolated",
                "--select",
                "E402",
                "--target-version",
                "py312",
                "--output-format=concise",
            ],
            "isolated-e402-all-detail.txt",
        ),
        # Config dump (may be large)
        (["check", "ruff.toml", "--show-settings"], "ruff-settings.txt"),
    ]
    for args, name in jobs:
        code, body = run(args)
        plain = strip_ansi(body)
        (OUT / name).write_text(f"$ {' '.join(args)}\nexit={code}\n\n{plain}", encoding="utf-8")
        print(name, "exit", code, "lines", plain.count("\n"))

    # Top files from wider concise
    wider = strip_ansi((OUT / "wider-concise.txt").read_text(encoding="utf-8"))
    files = Counter()
    rules = Counter()
    for line in wider.splitlines():
        # format: path:line:col: CODE message
        m = re.match(r"^([^:]+):\d+:\d+:\s+([A-Z]\d+)\s+", line)
        if m:
            files[m.group(1).replace("\\", "/")] += 1
            rules[m.group(2)] += 1
    summary = ["# Wider rule summary (E,F,W,I,UP,B,SIM)\n"]
    summary.append("## Top 20 rules\n")
    for code, n in rules.most_common(20):
        summary.append(f"- {code}: {n}\n")
    summary.append("\n## Top 30 files\n")
    for path, n in files.most_common(30):
        summary.append(f"- {n}\t{path}\n")
    summary.append(f"\nTotal findings parsed: {sum(rules.values())}\n")
    (OUT / "wider-summary.md").write_text("".join(summary), encoding="utf-8")
    print("wider total", sum(rules.values()), "unique files", len(files))

    # E402 noqa detail file counts
    e402 = strip_ansi((OUT / "detail-e402-noqa.txt").read_text(encoding="utf-8"))
    fhid = strip_ansi((OUT / "detail-f-noqa.txt").read_text(encoding="utf-8"))
    (OUT / "noqa-hidden-summary.md").write_text(
        "# noqa-hidden findings\n\n## E402\n```\n" + e402 + "\n```\n\n## F401/F841/F811\n```\n" + fhid + "\n```\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
