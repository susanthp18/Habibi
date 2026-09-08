"""Harvest completed workflow-agent results into durable per-agent files.

Why this exists: a workflow that dies on a session limit loses nothing — the
runtime appends every agent's return value to its journal the moment that agent
finishes. What it does lose is *addressability*: the journal keys results by an
opaque agentId, and the run directory is under a temp-ish session path. This
copies each result into audit-reports/agent-studio-nextgen/raw/ under a name
derived from the result's own content, so a later batch can read it back.

Usage (from D:\\Hackathon):
    python audit-reports/agent-studio-nextgen/harvest.py <runId> [<runId> ...]

Results are stored by the workflow as Python reprs, not JSON, so literal_eval is
the parser — json.loads would fail on every one of them.
"""

from __future__ import annotations

import ast
import json
import os
import sys

WORKFLOWS = os.path.expanduser(
    "~/.claude/projects/D--Hackathon/14d3f37b-1cc7-4a65-bb01-f4d0aeb59a70/subagents/workflows"
)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")


def slugify(text: str, limit: int = 44) -> str:
    """A filename that survives Windows and still says what it holds."""
    cleaned = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:limit].strip("-") or "unnamed"


def name_for(obj: object, agent_id: str) -> str:
    """Derive a stable name from the payload's own shape.

    Every schema in these workflows is distinguishable by a key it alone
    carries, so the file name does not depend on the label — which the journal
    does not record.
    """
    if not isinstance(obj, dict):
        return "text-%s" % agent_id[:6]
    if obj.get("slice"):
        kind = "verdicts" if "verdicts" in obj else "audit"
        return "%s-%s" % (kind, slugify(str(obj["slice"])))
    if "items" in obj:
        return "prior-%s" % agent_id[:6]
    if "scores" in obj:
        return "judge-%s" % agent_id[:6]
    if "verdicts" in obj:
        return "verdicts-%s" % agent_id[:6]
    if obj.get("name"):
        return "design-%s" % slugify(str(obj["name"]).split("—")[0])
    if "double_sources_of_truth" in obj:
        return "connectedness"
    return "result-%s" % agent_id[:6]


def harvest(run_id: str) -> int:
    journal = os.path.join(WORKFLOWS, run_id, "journal.jsonl")
    if not os.path.exists(journal):
        print("no journal for %s" % run_id, file=sys.stderr)
        return 0
    os.makedirs(OUT, exist_ok=True)
    written = 0
    with open(journal, encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "result":
                continue
            raw = entry.get("result")
            try:
                obj = ast.literal_eval(raw) if isinstance(raw, str) else raw
            except (ValueError, SyntaxError):
                # A plain-text agent (no schema) round-trips as itself.
                obj = raw
            agent_id = entry.get("agentId", "")
            base = name_for(obj, agent_id)
            if isinstance(obj, str):
                path = os.path.join(OUT, base + ".md")
                with open(path, "w", encoding="utf-8") as out:
                    out.write(obj)
            else:
                path = os.path.join(OUT, base + ".json")
                with open(path, "w", encoding="utf-8") as out:
                    json.dump(obj, out, indent=1, ensure_ascii=False)
            written += 1
            print("%-46s %8d  %s" % (base, len(raw or ""), agent_id[:8]))
    return written


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    total = sum(harvest(r) for r in sys.argv[1:])
    print("harvested %d result(s) into %s" % (total, OUT))
