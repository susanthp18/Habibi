"""Build a clean hackathon submission zip of D:\\Hackathon (code only)."""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(r"D:\Hackathon")
OUT = ROOT / "BigBound_AI_Hackathon_Submission.zip"

# Directory name segments to skip entirely
SKIP_DIR_NAMES = {
    ".git",
    ".agents",
    ".claude",
    ".cursor",
    ".idea",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".turbo",
    ".output",
    "dist",
    "build",
    "coverage",
    "pgdata",
    "minio_data",
    "voice_sessions",
}

# Exact relative paths (posix-style) to skip
SKIP_REL_PREFIXES = (
    "Docs/",  # large media / non-code dumps — keep product MD at root instead
)

SKIP_FILE_NAMES = {
    "ngrok.exe",
    ".mcp.json",
    ".DS_Store",
    "Thumbs.db",
    "logs.txt",
    "_make_submission_zip.py",
}

SKIP_SUFFIXES = (
    ".log",
    ".pyc",
    ".pyo",
    ".exe",
    ".zip",
)

SKIP_NAME_PREFIXES = (
    ".coderabbit",
    ".tmp_",
    "_tmp_",
    ".cr",
)

# Never ship secrets
SKIP_ENV_NAMES = {".env", ".env.local", ".env.production", ".env.development"}


def should_skip(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    parts = rel.parts
    if any(p in SKIP_DIR_NAMES for p in parts):
        return True

    rel_posix = rel.as_posix()
    if any(rel_posix == p.rstrip("/") or rel_posix.startswith(p) for p in SKIP_REL_PREFIXES):
        return True

    name = path.name
    if name in SKIP_FILE_NAMES or name in SKIP_ENV_NAMES:
        return True
    if name.endswith(SKIP_SUFFIXES):
        return True
    if any(name.startswith(pref) for pref in SKIP_NAME_PREFIXES):
        return True
    # Allow .env.example
    if name.startswith(".env") and name != ".env.example":
        return True
    return False


def main() -> None:
    if OUT.exists():
        OUT.unlink()

    count = 0
    total = 0
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if should_skip(path):
                continue
            # Don't include the output zip itself while writing
            if path.resolve() == OUT.resolve():
                continue
            arcname = Path("BigBound_AI") / path.relative_to(ROOT)
            zf.write(path, arcname.as_posix())
            count += 1
            total += path.stat().st_size

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote: {OUT}")
    print(f"Files: {count}")
    print(f"Uncompressed source: {total / (1024 * 1024):.1f} MB")
    print(f"Zip size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
