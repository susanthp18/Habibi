"""Run ruff audits and write UTF-8 reports. Check-only; never --fix."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(r"D:\Hackathon\backend")
OUT = Path(r"D:\Hackathon\artifacts")
RUFF = BACKEND / ".venv" / "Scripts" / "ruff.exe"


def run(args: list[str], out_name: str) -> int:
    cmd = [str(RUFF), *args]
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    body = (proc.stdout or "") + (proc.stderr or "")
    (OUT / out_name).write_text(
        f"$ {' '.join(args)}\nexit={proc.returncode}\n\n{body}",
        encoding="utf-8",
    )
    print(out_name, "exit", proc.returncode, "bytes", len(body.encode()))
    return proc.returncode


def main() -> int:
    if not RUFF.exists():
        print("missing", RUFF)
        return 2
    ver = subprocess.run([str(RUFF), "--version"], capture_output=True, text=True)
    (OUT / "ruff-venv-version.txt").write_text(ver.stdout + ver.stderr, encoding="utf-8")
    print("version:", (ver.stdout or ver.stderr).strip())

    run(["check", ".", "--statistics"], "ruff-stats-utf8.txt")
    run(["check", ".", "--output-format=concise"], "ruff-concise-utf8.txt")
    run(
        ["check", ".", "--select", "F401,F841,F811,E402", "--statistics"],
        "ruff-f-stats-utf8.txt",
    )
    run(
        ["check", ".", "--select", "E402", "--ignore-noqa", "--statistics"],
        "ruff-e402-ignore-noqa-utf8.txt",
    )
    run(
        ["check", ".", "--select", "F401,F841,F811", "--ignore-noqa", "--statistics"],
        "ruff-f-ignore-noqa-utf8.txt",
    )
    run(
        [
            "check",
            "voice/bot.py",
            "worker.py",
            "bot_worker.py",
            "voice/spike.py",
            "--select",
            "E402",
            "--statistics",
        ],
        "ruff-e402-entrypoints-utf8.txt",
    )
    # Without per-file ignores: run entrypoints with ignore-noqa too
    run(
        [
            "check",
            "voice/bot.py",
            "worker.py",
            "bot_worker.py",
            "voice/spike.py",
            "--select",
            "E402",
            "--ignore-noqa",
            "--output-format=concise",
        ],
        "ruff-e402-entrypoints-detail-utf8.txt",
    )
    run(
        ["check", ".", "--select", "E,F,W,I,UP,B,SIM", "--statistics"],
        "ruff-wider-utf8.txt",
    )
    # Top files for wider rules if any
    run(
        ["check", ".", "--select", "E,F,W,I,UP,B,SIM", "--output-format=concise"],
        "ruff-wider-concise-utf8.txt",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
