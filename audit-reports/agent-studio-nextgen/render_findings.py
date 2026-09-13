"""Render the complete findings reference from the verified evidence.

The argument lives in docs/design/AGENT_STUDIO_NEXT_GEN.md; this generates its companion —
every finding in full, plus the cross-cutting inventories that are not findings
at all (a drift pair or a doc-vs-code contradiction has no single site to pin an
id to) and the critic's gaps in the audit itself.

Regenerate after any change to backlog.json:
    python audit-reports/agent-studio-nextgen/render_findings.py
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(REPO, "docs", "design", "AGENT_STUDIO_FINDINGS.md")

# Slice key -> the screen an engineer would open. Ordered by the fix-loop order
# in docs/design/AGENT_STUDIO_NEXT_GEN.md §5, so reading top to bottom is the work order.
SLICES = [
    ("ship", "Ship tab — canary, shadow, auto-rollback, deployments"),
    ("evals", "Evals tab — suites, reports, and the publish gates"),
    ("skills", "Skills — card tab, library, detail, packs, signing"),
    ("connectors", "Connectors — tab, registry, ext.* dispatch"),
    ("changelog", "Change log — the hash chain and what it covers"),
    ("guardrails", "Guardrails tab — six toggles, two sliders, banned words"),
    ("outbound", "Outbound tab — direction, missions, cadences, post-call, pools"),
    ("flow", "Flow tab — canvas, inspector, validator, the two runtimes"),
    ("tools", "Tools tab — grant vs offer, locked engines, voice cap"),
    ("catalog", "Tool catalog — 26 specs across voice, text, MCP and flow"),
    ("graph", "Agent graph tab — handoffs and the handoff runtime"),
    ("sandbox", "Sandbox — parity between what you test and what you ship"),
    ("fleet", "Fleet index — roster, clone, archive, reachability"),
    ("prompt", "System Prompt tab — lint, token estimate, the render path"),
    ("persona", "Persona tab — traits, presets, language"),
    ("voice", "Voice (TTS) tab — catalog, params, preview, runtime binding"),
    ("bindings", "Bindings tab — provider models per slot"),
    ("policy", "Policy tab — the six locked engines"),
    ("shell", "Card editor shell — hydration, autosave, drafts, publish"),
    ("header", "Header and version history"),
    ("runtime", "Agent Card → runtime — the field-by-field inventory"),
    ("types", "Type mirror — TypeScript vs Pydantic"),
    ("authz", "Authorization, tenancy and audit on every studio write"),
    ("org", "Code organization, duplication, dead code, test gaps"),
]

SEVERITY_ORDER = {"MAJOR": 0, "MINOR": 1, "TRIVIAL": 2}
BADGE = {"MAJOR": "**MAJOR**", "MINOR": "MINOR", "TRIVIAL": "trivial"}


def code_list(paths: list[str]) -> str:
    return ", ".join("`%s`" % p for p in paths) if paths else "—"


def render_finding(f: dict) -> str:
    out = ["#### `%s` — %s\n" % (f["id"], f["title"])]
    bits = [BADGE[f["severity"]], f["category"]]
    # Only worth printing when it is not the ordinary case; CONFIRMED is the norm
    # and saying so 337 times is noise.
    if f["status"] != "CONFIRMED":
        bits.append(f["status"])
    if f.get("prior_ref"):
        bits.append("prior: %s" % f["prior_ref"])
    if f.get("closed_in"):
        bits.append("**closed** in `%s` (pass %s)" % (f["closed_in"], f.get("pass", "?")))
    elif f.get("deferred"):
        bits.append("deferred: %s" % f["deferred"])
    out.append("%s\n" % " · ".join(bits))
    out.append("**Files** — %s\n" % code_list(f["files"]))
    out.append("**Mechanism** — %s\n" % f["mechanism"])
    out.append("**Trigger** — %s\n" % f["trigger"])
    out.append("**Fix** — %s\n" % f["fix"])
    return "\n".join(out)


def render_findings(rows: list) -> list[str]:
    by_slice: dict[str, list] = {}
    for row in rows:
        by_slice.setdefault(row["slice"], []).append(row)

    parts: list[str] = []
    for key, title in SLICES:
        band = sorted(by_slice.get(key, []), key=lambda f: (SEVERITY_ORDER[f["severity"]], f["id"]))
        if not band:
            continue
        counts = {s: sum(1 for f in band if f["severity"] == s) for s in ("MAJOR", "MINOR", "TRIVIAL")}
        closed = sum(1 for f in band if f.get("closed_in"))
        parts.append("---\n\n## %s\n" % title)
        parts.append(
            "%d findings — %d MAJOR, %d MINOR, %d trivial; %d recorded closed in `raw/closures.json`.\n"
            % (len(band), counts["MAJOR"], counts["MINOR"], counts["TRIVIAL"], closed)
        )
        parts.append("What this slice is, end to end, is in `raw/audit-%s.json` (`summary`, "
                     "`endpoints`, `runtime_consumers`, `checked_fine`).\n" % key)
        for f in band:
            parts.append(render_finding(f))

    unknown = sorted(set(by_slice) - {k for k, _ in SLICES})
    for key in unknown:  # a slice added later must not vanish silently
        band = sorted(by_slice[key], key=lambda f: (SEVERITY_ORDER[f["severity"]], f["id"]))
        parts.append("---\n\n## %s\n" % key)
        for f in band:
            parts.append(render_finding(f))
    return parts


def render_crosscutting() -> list[str]:
    conn = json.load(open(os.path.join(RAW, "connectedness.json"), encoding="utf-8"))
    parts = ["---\n\n# Cross-cutting inventories\n"]
    parts.append(
        "These are not findings and carry no ids: a drift pair, a dependency between two tabs "
        "or a contradiction between a doc and the code has no single site to pin one to. They "
        "come from the connectedness pass over all 24 slices (`raw/connectedness.json`).\n"
    )

    dsot = conn["double_sources_of_truth"]
    drifted = [d for d in dsot if d["already_drifted"]]
    parts.append("## Double sources of truth (%d, of which %d have already drifted)\n" % (len(dsot), len(drifted)))
    parts.append(
        "Every duplicated vocabulary in this slice that was given a cross-language drift test has "
        "held; every one that was not has drifted. Collapsing a pair onto one owner is only half "
        "the fix — the test is the half that keeps it collapsed.\n"
    )
    for d in sorted(dsot, key=lambda x: not x["already_drifted"]):
        parts.append("### %s%s\n" % (d["name"], "  ⚠️ **already drifted**" if d["already_drifted"] else ""))
        parts.append("\n".join("- `%s`" % c for c in d["copies"]) + "\n")
        parts.append("**Risk** — %s\n" % d["risk"])

    for key, heading, blurb in [
        ("writes_without_readers", "Studio writes with no runtime reader",
         "Grouped by tab. Each is a W4 decision: connect it, or delete it from schema, type, UI and gate in one commit."),
        ("readers_without_writers", "Runtime behaviour no tab can author",
         "The inverse: real behaviour that needs a code deploy to change, and where an operator would reasonably go looking for it."),
        ("disconnected_controls", "Controls that call nothing, or whose effect is observable nowhere",
         "Each names what a user reasonably expects the control to do."),
        ("tab_dependencies", "Where one tab's edit changes another tab's validity",
         "And whether the studio surfaces it live, only at publish, or never."),
        ("doc_vs_code", "Documentation and UI copy the code contradicts",
         "Both sides cited. Fixing one of these means changing the code or the sentence — deciding which is the point."),
    ]:
        items = conn[key]
        parts.append("## %s (%d)\n" % (heading, len(items)))
        parts.append("%s\n" % blurb)
        parts.append("\n".join("- %s" % i for i in items) + "\n")
    return parts


def render_gaps() -> list[str]:
    path = os.path.join(RAW, "completeness-critic.md")
    gaps = [ln.strip() for ln in open(path, encoding="utf-8") if ln.startswith("GAP:")]
    parts = ["---\n\n# Gaps in this audit (%d)\n" % len(gaps)]
    parts.append(
        "A critic re-read the audit against the source, looking for what the 24 slices missed: "
        "control-surface entries no slice mentioned, backend routes no slice listed, `checked_fine` "
        "claims that are wrong, and defect classes a static read cannot reach. Each line is "
        "*what — why it matters — what to read or run*. These are work, not caveats.\n"
    )
    parts.append("\n".join("- %s" % g[len("GAP:"):].strip() for g in gaps) + "\n")
    return parts


def main() -> None:
    rows = json.load(open(os.path.join(HERE, "backlog.json"), encoding="utf-8"))
    counts = {s: sum(1 for f in rows if f["severity"] == s) for s in ("MAJOR", "MINOR", "TRIVIAL")}

    head = [
        "# Agent Studio — the complete findings\n",
        "**Generated** from `audit-reports/agent-studio-nextgen/` by `render_findings.py`. "
        "Do not edit by hand; edit `backlog.json` and regenerate.\n",
        "The argument, the architecture and the work plan are in "
        "[AGENT_STUDIO_NEXT_GEN.md](./AGENT_STUDIO_NEXT_GEN.md). This is its reference half: "
        "every finding in full, then the cross-cutting inventories, then the gaps in the audit itself.\n",
        "**%d findings — %d MAJOR, %d MINOR, %d trivial — across %d slices.** Every one was "
        "adversarially verified by a second agent instructed to refute it; the two that were "
        "refuted are excluded. Severity: MAJOR = wrong runtime behaviour, wrong publish verdict, "
        "silent data loss, a lie to the operator, or a regulated-path defect; MINOR = incorrect "
        "but contained; trivial = cosmetic.\n"
        % (len(rows), counts["MAJOR"], counts["MINOR"], counts["TRIVIAL"], len(set(r["slice"] for r in rows))),
        "Line numbers were accurate when read against commit `026cada`, in a tree that was moving "
        "(see the working-tree caveat in the companion). **Re-anchor every citation before acting "
        "on it.**\n",
        "**Closure is recorded per finding in `raw/closures.json`** — %d closed (every MAJOR, by the "
        "re-verification of 2026-09-09 and its same-day commits; the pass-7 residue by commit), "
        "%d deferred with the reason named. A MINOR or trivial finding with no closure line was "
        "worked under a MASTER-BACKLOG work package (passes 3–6) and has not been re-verified by "
        "id, so it is not claimed closed here.\n"
        % (sum(1 for f in rows if f.get("closed_in")), sum(1 for f in rows if f.get("deferred"))),
        "## Contents\n",
    ]
    by_slice = {}
    for row in rows:
        by_slice.setdefault(row["slice"], []).append(row)
    for key, title in SLICES:
        band = by_slice.get(key, [])
        if band:
            anchor = title.lower().replace(" — ", "--").replace(" ", "-")
            for ch in "(),.*`":
                anchor = anchor.replace(ch, "")
            head.append("- [%s](#%s) — %d findings, %d MAJOR"
                        % (title, anchor, len(band),
                           sum(1 for f in band if f["severity"] == "MAJOR")))
    head.append("- [Cross-cutting inventories](#cross-cutting-inventories)")
    head.append("- [Gaps in this audit](#gaps-in-this-audit-33)\n")

    body = head + render_findings(rows) + render_crosscutting() + render_gaps()
    text = "\n".join(body)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s — %d findings, %d lines, %d KB"
          % (OUT, len(rows), text.count("\n") + 1, len(text.encode("utf-8")) / 1024))


if __name__ == "__main__":
    main()
