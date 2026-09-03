"""Read-only TypeScript integrity scanner for Habibi/src (no node_modules)."""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

ROOT = r"D:\Hackathon\Habibi"
SCAN_DIRS = [
    os.path.join(ROOT, "src"),
    os.path.join(ROOT, "scripts"),
]
SCAN_FILES = [
    os.path.join(ROOT, "vite.config.ts"),
    os.path.join(ROOT, "vitest.config.ts"),
    os.path.join(ROOT, "eslint.config.js"),
]
SKIP_DIR = {"node_modules", "dist", ".output", ".vinxi", "cover"}
EXTS = {".ts", ".tsx", ".mts", ".cts", ".js", ".mjs"}

PATTERNS = {
    "ts_ignore": re.compile(r"@ts-ignore"),
    "ts_expect": re.compile(r"@ts-expect-error"),
    "ts_nocheck": re.compile(r"@ts-nocheck"),
    "as_any": re.compile(r"\bas any\b"),
    "colon_any": re.compile(r": any\b"),
    "angle_any": re.compile(r"<any>"),
    "as_unknown_as": re.compile(r"as unknown as"),
    "as_never": re.compile(r"\bas never\b"),
    "as_const": re.compile(r"\bas const\b"),
    "json_parse": re.compile(r"JSON\.parse\("),
    "zod_import": re.compile(r"""from ['"]zod(?:/v[34])?['"]"""),
    "zod_use": re.compile(r"\bz\."),
    "satisfies": re.compile(r"\bsatisfies\b"),
    "eslint_any": re.compile(r"no-explicit-any|no-unsafe-"),
    "apiGet": re.compile(r"apiGet<"),
    "apiPost": re.compile(r"apiPost<"),
    "apiPatch": re.compile(r"apiPatch<"),
    "undefined_as_T": re.compile(r"undefined as T"),
    "json_as_T": re.compile(r"JSON\.parse\([^)]*\) as "),
    "res_json_as": re.compile(r"res\.json\(\)\) as "),
    "validateSearch": re.compile(r"validateSearch"),
    "zodValidator": re.compile(r"zodValidator|zod\.|z\.object"),
    "useQuery_any": re.compile(r"useQuery<\s*any"),
    "Record_string_any": re.compile(r"Record<string,\s*any>"),
    "Record_string_unknown": re.compile(r"Record<string,\s*unknown>"),
    "as_cast": re.compile(r"\bas (?!const\b)(?!any\b)(?!unknown\b)(?!never\b)([A-Za-z_][A-Za-z0-9_.<>,\[\] |&?]*)"),
    "nonnull_bang": re.compile(r"[\w)\]]!(?![!=])"),
    "catch_any": re.compile(r"catch\s*\(\s*\w+\s*:\s*any"),
    "from_seed": re.compile(r"""from ["']@/data/[^"']+-seed["']"""),
    "export_type": re.compile(r"^export (?:type|interface) "),
}

SEED_EXPORT = re.compile(
    r"^export (?:type|interface) (\w+)",
)
DUP_NAMES = [
    "Channel",
    "Customer",
    "Promise",
    "Callback",
    "Consent",
    "DocumentRequest",
    "DocRequest",
    "Offer",
    "AgentCard",
    "WorkItem",
    "Handoff",
    "Invoice",
    "Dispute",
    "Interaction",
    "Thread",
    "Billing",
]


def iter_files():
    for d in SCAN_DIRS:
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIR and not x.startswith(".")]
            for fn in filenames:
                if os.path.splitext(fn)[1] in EXTS and "routeTree.gen" not in fn:
                    yield os.path.join(dirpath, fn)
    for f in SCAN_FILES:
        if os.path.isfile(f):
            yield f


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def main() -> None:
    hits: dict[str, list[str]] = defaultdict(list)
    seed_types: dict[str, list[str]] = defaultdict(list)
    named_types: dict[str, list[str]] = defaultdict(list)
    file_count = 0
    line_count = 0

    for path in iter_files():
        file_count += 1
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            print("READERR", rel(path), e, file=sys.stderr)
            continue
        r = rel(path)
        is_seed = "-seed.ts" in r
        for i, line in enumerate(lines, 1):
            line_count += 1
            stripped = line.rstrip()
            for k, pat in PATTERNS.items():
                if pat.search(line):
                    hits[k].append(f"{r}:{i}:{stripped[:200]}")
            if is_seed:
                m = SEED_EXPORT.search(line)
                if m:
                    seed_types[m.group(1)].append(f"{r}:{i}")
            m2 = SEED_EXPORT.search(line)
            if m2 and m2.group(1) in DUP_NAMES:
                named_types[m2.group(1)].append(f"{r}:{i}")

    print(f"FILES {file_count}")
    print(f"LINES {line_count}")
    for k in PATTERNS:
        print(f"COUNT {k} {len(hits[k])}")

    def dump(name: str, limit: int = 200) -> None:
        print(f"---{name}---")
        rows = hits[name]
        print("\n".join(rows[:limit] or ["NONE"]))
        if len(rows) > limit:
            print(f"... {len(rows) - limit} more")

    for name in [
        "ts_ignore",
        "ts_expect",
        "ts_nocheck",
        "as_any",
        "colon_any",
        "angle_any",
        "as_unknown_as",
        "as_never",
        "zod_import",
        "zod_use",
        "json_parse",
        "json_as_T",
        "undefined_as_T",
        "validateSearch",
        "zodValidator",
        "useQuery_any",
        "Record_string_any",
        "catch_any",
        "eslint_any",
        "from_seed",
    ]:
        dump(name)

    print("---SATISFIES_COUNT---", len(hits["satisfies"]))
    print("---AS_CONST_COUNT---", len(hits["as_const"]))
    print("---AS_CAST_COUNT---", len(hits["as_cast"]))
    print("---NONNULL_COUNT---", len(hits["nonnull_bang"]))
    print("---RECORD_UNKNOWN_COUNT---", len(hits["Record_string_unknown"]))

    print("---SEED_TYPES---")
    for name, locs in sorted(seed_types.items()):
        print(f"{name}: {', '.join(locs)}")

    print("---NAMED_TYPE_HOMES---")
    for name, locs in sorted(named_types.items()):
        print(f"{name}:")
        for loc in locs:
            print(f"  {loc}")

    print("---FROM_SEED_FILES---")
    by_file = defaultdict(int)
    for row in hits["from_seed"]:
        by_file[row.split(":")[0]] += 1
    for f, n in sorted(by_file.items(), key=lambda x: -x[1]):
        print(f"{n:3} {f}")


if __name__ == "__main__":
    main()
