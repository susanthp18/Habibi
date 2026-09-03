"""Frontend layer scan for Habibi/src. Regex imports only."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\Hackathon\Habibi\src")
IMP = re.compile(r"""from\s+['"](@/[^'"]+)['"]""")

SKIP = {".test.ts", ".test.tsx"}


def bucket(path: str) -> str:
    # path like api/foo.ts or components/prompt-studio/X.tsx
    if path.startswith("routes/"):
        return "routes"
    if path.startswith("components/ui/") or path.startswith("components/charts/") or path.startswith("components/brand/") or path.startswith("components/shell/"):
        return "ui"
    if path.startswith("components/"):
        # feature name
        parts = path.split("/")
        return "feature:" + parts[1]
    if path.startswith("api/"):
        return "api"
    if path.startswith("data/"):
        return "data"
    if path.startswith("lib/"):
        return "lib"
    if path.startswith("hooks/"):
        return "hooks"
    return "other"


def feature_of_alias(alias: str) -> str | None:
    # @/components/prompt-studio/X
    if alias.startswith("@/components/"):
        rest = alias[len("@/components/") :]
        name = rest.split("/")[0]
        if name in {"ui", "charts", "brand", "shell"}:
            return None  # shared
        return name
    return None


def main() -> None:
    files = [p for p in ROOT.rglob("*") if p.suffix in {".ts", ".tsx"} and "routeTree.gen" not in p.name]
    edges = []
    api_imports_ui = []
    data_used_as_logic = []
    cross_feature = []
    seed_exports_fns = defaultdict(list)

    for p in files:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        src = p.read_text(encoding="utf-8")
        src_b = bucket(rel)
        for m in IMP.finditer(src):
            alias = m.group(1)
            tgt = alias[2:]  # strip @/
            edges.append((rel, alias, src_b, bucket(tgt)))
            if src_b == "api" and (tgt.startswith("components/") and not tgt.startswith("components/ui")):
                api_imports_ui.append((rel, alias))
            # feature → other feature
            if src_b.startswith("feature:"):
                src_feat = src_b.split(":", 1)[1]
                dst_feat = feature_of_alias(alias)
                if dst_feat and dst_feat != src_feat:
                    cross_feature.append((src_feat, dst_feat, rel, alias))

        if rel.startswith("data/") and p.suffix == ".ts":
            # exported functions (not types)
            for fm in re.finditer(r"^export function (\w+)", src, re.M):
                seed_exports_fns[rel].append(fm.group(1))
            for fm in re.finditer(r"^export const (\w+)\s*=\s*(?:\(|async|function)", src, re.M):
                seed_exports_fns[rel].append(fm.group(1))
            # also export { foo } of helpers is harder; catch named function decls
            for fm in re.finditer(r"^export function (\w+)|^function (\w+)\(", src, re.M):
                name = fm.group(1) or fm.group(2)
                if name not in seed_exports_fns[rel]:
                    seed_exports_fns[rel].append(name)

    # fan
    fan_in = defaultdict(set)
    fan_out = defaultdict(set)
    # module = directory for features, file for api/data/lib
    def node(rel: str) -> str:
        b = bucket(rel)
        if b.startswith("feature:"):
            return b
        if rel.startswith("api/"):
            return "api:" + Path(rel).stem
        if rel.startswith("data/"):
            return "data:" + Path(rel).stem
        if rel.startswith("lib/"):
            return "lib:" + Path(rel).stem
        if rel.startswith("routes/"):
            return "routes"
        return b

    for rel, alias, sb, tb in edges:
        a = node(rel)
        tgt = alias[2:]
        b = node(tgt) if not tgt.endswith(".ts") else node(tgt)
        # rough
        if tgt.startswith("api/"):
            b = "api:" + tgt.split("/")[1].split(".")[0]
        elif tgt.startswith("data/"):
            b = "data:" + tgt.split("/")[1].split(".")[0]
        elif tgt.startswith("lib/"):
            b = "lib:" + tgt.split("/")[1].split(".")[0]
        elif tgt.startswith("components/"):
            feat = tgt.split("/")[1]
            b = "ui" if feat in {"ui", "charts", "brand", "shell"} else "feature:" + feat
        elif tgt.startswith("routes/"):
            b = "routes"
        if a != b:
            fan_out[a].add(b)
            fan_in[b].add(a)

    ranking = []
    nodes = set(fan_in) | set(fan_out)
    for n in nodes:
        fi, fo = len(fan_in[n]), len(fan_out[n])
        if fi + fo == 0:
            continue
        I = fo / (fi + fo)
        ranking.append((n, fi, fo, round(I, 3), fi * fo))
    ranking.sort(key=lambda x: -x[4])

    # unique cross-feature pairs
    pairs = defaultdict(list)
    for sf, df, rel, alias in cross_feature:
        pairs[(sf, df)].append((rel, alias))

    out = {
        "files": len(files),
        "import_edges": len(edges),
        "api_imports_ui": api_imports_ui,
        "cross_feature_pairs": {f"{a}->{b}": v[:8] for (a, b), v in sorted(pairs.items(), key=lambda kv: -len(kv[1]))},
        "cross_feature_counts": {f"{a}->{b}": len(v) for (a, b), v in sorted(pairs.items(), key=lambda kv: -len(kv[1]))},
        "seed_exported_fns": {k: v for k, v in seed_exports_fns.items() if v},
        "central": ranking[:20],
        "api_fan_in_top": sorted(((n, len(fan_in[n])) for n in nodes if n.startswith("api:")), key=lambda x: -x[1])[:15],
        "data_fan_in_top": sorted(((n, len(fan_in[n])) for n in nodes if n.startswith("data:")), key=lambda x: -x[1])[:15],
    }
    Path(r"D:\Hackathon\_arch_frontend.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("files", len(files), "edges", len(edges))
    print("api→ui", api_imports_ui)
    print("cross-feature counts", out["cross_feature_counts"])
    print("seed fns:")
    for k, v in seed_exports_fns.items():
        if v:
            print(" ", k, v)
    print("central", ranking[:12])


if __name__ == "__main__":
    main()
