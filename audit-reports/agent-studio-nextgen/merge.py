"""Merge slice audits with their adversarial verdicts into one ranked backlog.

A finding is only as good as its verdict, so this drops anything REFUTED,
applies the verifier's corrected severity and file lines where it supplied
them, and marks anything that never reached a verifier as UNVERIFIED rather
than quietly promoting it. UNVERIFIED is a real state — the first audit run
lost its verifiers to a session limit — and printing it as such is the whole
reason this file exists instead of a one-liner.

Usage (from D:\\Hackathon):
    python audit-reports/agent-studio-nextgen/merge.py            # summary
    python audit-reports/agent-studio-nextgen/merge.py --json     # full backlog
"""

from __future__ import annotations

import glob
import json
import os
import sys

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
SEVERITY_ORDER = {"MAJOR": 0, "MINOR": 1, "TRIVIAL": 2}
# Verdicts whose findings still belong in the backlog.
SURVIVES = {"CONFIRMED", "DOWNGRADED", "UNVERIFIED"}


def load_audits() -> dict:
    """slice -> audit report. Skips the prior-status file, which has no findings."""
    out = {}
    for path in sorted(glob.glob(os.path.join(RAW, "audit-*.json"))):
        report = json.load(open(path, encoding="utf-8"))
        if "items" in report:  # prior-status agent, different schema
            continue
        out[report["slice"]] = report
    return out


def load_verdicts() -> dict:
    """slice -> {finding id: verdict}."""
    out = {}
    for path in sorted(glob.glob(os.path.join(RAW, "verdicts-*.json"))):
        block = json.load(open(path, encoding="utf-8"))
        out[block["slice"]] = {v["id"]: v for v in block["verdicts"]}
    return out


def load_closures() -> dict:
    """finding id -> {closed_in, pass, evidence} or {deferred, pass}.

    raw/closures.json is the closure ledger: a finding is closed when a
    commit (or a re-verification table) says so, and deferred when a named
    reason keeps it open. Nothing else in this pipeline changes a status.
    """
    path = os.path.join(RAW, "closures.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def merge() -> list:
    audits, verdicts = load_audits(), load_verdicts()
    closures = load_closures()
    merged = []
    for slice_name, report in audits.items():
        by_id = verdicts.get(slice_name, {})
        for finding in report.get("findings", []):
            verdict = by_id.get(finding["id"])
            status = verdict["verdict"] if verdict else "UNVERIFIED"
            if status not in SURVIVES:
                continue
            corrected = (verdict or {}).get("corrected_severity") or ""
            files = (verdict or {}).get("corrected_files") or []
            merged.append(
                {
                    **finding,
                    "slice": slice_name,
                    "severity": corrected or finding["severity"],
                    "status": status,
                    "files": files or finding["files"],
                    "verify_reason": (verdict or {}).get("reason", ""),
                    **closures.get(finding["id"], {}),
                }
            )
    merged.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["slice"], f["id"]))
    return merged


def dropped() -> list:
    """Findings a verifier killed — kept visible so nobody re-files them."""
    audits, verdicts = load_audits(), load_verdicts()
    out = []
    for slice_name, report in audits.items():
        by_id = verdicts.get(slice_name, {})
        for finding in report.get("findings", []):
            verdict = by_id.get(finding["id"])
            if verdict and verdict["verdict"] not in SURVIVES:
                out.append((finding["id"], verdict["verdict"], finding["title"], verdict["reason"]))
    return out


if __name__ == "__main__":
    rows = merge()
    if "--json" in sys.argv:
        # A file, not stdout: this console is cp1252 and the findings are full of
        # set-notation and en-dashes, so printing them raises UnicodeEncodeError
        # on the very characters that make a mechanism readable.
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backlog.json")
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, indent=1, ensure_ascii=False)
        print("wrote %d findings to %s" % (len(rows), out))
        raise SystemExit(0)

    for severity in ("MAJOR", "MINOR", "TRIVIAL"):
        band = [f for f in rows if f["severity"] == severity]
        print("\n===== %s (%d) =====" % (severity, len(band)))
        for f in band:
            flag = "" if f["status"] == "CONFIRMED" else " [%s]" % f["status"]
            print("%-14s %-16s %s%s" % (f["id"], f["category"], f["title"], flag))

    killed = dropped()
    if killed:
        print("\n===== dropped by verification (%d) =====" % len(killed))
        for fid, verdict, title, reason in killed:
            print("%-14s %-20s %s" % (fid, verdict, title))
            print("               %s" % reason[:200])

    closed = sum(1 for f in rows if f.get("closed_in"))
    deferred = sum(1 for f in rows if f.get("deferred"))
    print(
        "\ntotal in backlog: %d  (unverified: %d, closed: %d, deferred: %d, open: %d)"
        % (
            len(rows),
            sum(1 for f in rows if f["status"] == "UNVERIFIED"),
            closed,
            deferred,
            len(rows) - closed - deferred,
        )
    )
