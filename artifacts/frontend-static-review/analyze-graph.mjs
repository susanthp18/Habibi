#!/usr/bin/env node
/**
 * Read-only TypeScript import graph for Habibi/src.
 * Resolves @/* aliases and relative imports. Skips node_modules.
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = "D:/Hackathon/Habibi";
const SRC = path.join(ROOT, "src");
const EXTS = [".ts", ".tsx", ".js", ".jsx"];
const SKIP_DIRS = new Set(["node_modules", "dist", ".output"]);

function walk(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(ent.name)) continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(ent.name)) out.push(p);
  }
  return out;
}

function rel(p) {
  return path.relative(SRC, p).replaceAll("\\", "/");
}

function layerOf(fileRel) {
  if (fileRel === "routeTree.gen.ts") return "generated";
  const top = fileRel.split("/")[0];
  if (top === "routes") return "routes";
  if (top === "components") return "components";
  if (top === "api") return "api";
  if (top === "data") return "data";
  if (top === "lib") return "lib";
  if (top === "hooks") return "hooks";
  if (top === "types") return "types";
  if (fileRel === "router.tsx" || fileRel === "server.ts") return "entry";
  return "other";
}

function resolveImport(fromFile, spec) {
  if (spec.startsWith("@/")) {
    return resolvePath(path.join(SRC, spec.slice(2)));
  }
  if (spec.startsWith(".")) {
    return resolvePath(path.join(path.dirname(fromFile), spec));
  }
  return null; // external
}

function resolvePath(base) {
  const candidates = [];
  const stripped = base.replace(/\.(ts|tsx|js|jsx)$/, "");
  for (const ext of EXTS) {
    candidates.push(stripped + ext);
    candidates.push(path.join(stripped, "index" + ext));
  }
  candidates.push(base);
  for (const c of candidates) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return path.normalize(c);
  }
  return null;
}

const IMPORT_RE =
  /(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?\sfrom\s*)?["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)|require\s*\(\s*["']([^"']+)["']\s*\)/g;

const files = walk(SRC);
const nodes = new Set(files.map(rel));
const adj = new Map(); // from -> Set(to)
const inbound = new Map();
for (const n of nodes) {
  adj.set(n, new Set());
  inbound.set(n, new Set());
}

const unresolved = [];
const externalCounts = new Map();
let edgeCount = 0;
const typeOnlyEdges = [];

for (const abs of files) {
  const from = rel(abs);
  const text = fs.readFileSync(abs, "utf8");
  // strip comments roughly
  const cleaned = text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
  const specs = new Set();
  let m;
  const re = new RegExp(IMPORT_RE.source, "g");
  while ((m = re.exec(cleaned))) {
    const spec = m[1] || m[2] || m[3];
    if (spec) specs.add(spec);
  }
  // also catch `export { x } from "..."` already covered
  for (const spec of specs) {
    const resolved = resolveImport(abs, spec);
    if (!resolved) {
      if (!spec.startsWith(".") && !spec.startsWith("@/")) {
        const pkg = spec.startsWith("@")
          ? spec.split("/").slice(0, 2).join("/")
          : spec.split("/")[0];
        externalCounts.set(pkg, (externalCounts.get(pkg) || 0) + 1);
      } else {
        unresolved.push({ from, spec });
      }
      continue;
    }
    const to = rel(resolved);
    if (!nodes.has(to)) continue;
    if (to === from) continue;
    if (!adj.get(from).has(to)) {
      adj.get(from).add(to);
      inbound.get(to).add(from);
      edgeCount++;
    }
  }
}

function tarjan(graph) {
  const index = new Map();
  const low = new Map();
  const stack = [];
  const onStack = new Set();
  const sccs = [];
  let i = 0;
  function strong(v) {
    index.set(v, i);
    low.set(v, i);
    i++;
    stack.push(v);
    onStack.add(v);
    for (const w of graph.get(v) || []) {
      if (!index.has(w)) {
        strong(w);
        low.set(v, Math.min(low.get(v), low.get(w)));
      } else if (onStack.has(w)) {
        low.set(v, Math.min(low.get(v), index.get(w)));
      }
    }
    if (low.get(v) === index.get(v)) {
      const scc = [];
      let w;
      do {
        w = stack.pop();
        onStack.delete(w);
        scc.push(w);
      } while (w !== v);
      if (scc.length > 1) sccs.push(scc);
      else {
        // self-loop
        if ((graph.get(v) || new Set()).has(v)) sccs.push(scc);
      }
    }
  }
  for (const v of graph.keys()) if (!index.has(v)) strong(v);
  return sccs;
}

function simpleCycles(graph) {
  // DFS for cycles of length >= 2, canonicalized
  const found = [];
  const seenCanon = new Set();
  for (const start of graph.keys()) {
    const stack = [start];
    const pathSet = new Set([start]);
    function dfs(v) {
      for (const w of graph.get(v) || []) {
        if (w === start && stack.length >= 2) {
          const cyc = [...stack, start];
          const rot = cyc.slice(0, -1);
          const minI = rot.reduce((mi, x, i) => (x < rot[mi] ? i : mi), 0);
          const canon = [...rot.slice(minI), ...rot.slice(0, minI)].join("→");
          if (!seenCanon.has(canon)) {
            seenCanon.add(canon);
            found.push([...rot.slice(minI), ...rot.slice(0, minI), rot[minI]]);
          }
        } else if (!pathSet.has(w) && stack.length < 8) {
          stack.push(w);
          pathSet.add(w);
          dfs(w);
          stack.pop();
          pathSet.delete(w);
        }
      }
    }
    dfs(start);
  }
  return found;
}

const sccs = tarjan(adj);
const cycles = simpleCycles(adj);

const fanIn = [...nodes]
  .map((n) => ({ file: n, in: inbound.get(n).size, out: adj.get(n).size }))
  .sort((a, b) => b.in - a.in);

const fanOut = [...nodes]
  .map((n) => ({ file: n, in: inbound.get(n).size, out: adj.get(n).size }))
  .sort((a, b) => b.out - a.out);

const orphans = [...nodes].filter((n) => inbound.get(n).size === 0);
const leaves = [...nodes].filter((n) => adj.get(n).size === 0);

function topDir(n) {
  const i = n.indexOf("/");
  return i === -1 ? n : n.slice(0, i);
}

const byDir = {};
for (const n of nodes) {
  const d = topDir(n);
  byDir[d] = (byDir[d] || 0) + 1;
}

const componentDirs = {};
for (const n of nodes) {
  if (!n.startsWith("components/")) continue;
  const parts = n.split("/");
  const d = parts[1] || "(file)";
  componentDirs[d] = (componentDirs[d] || 0) + 1;
}

// Layer edges
const layerEdges = {};
const violations = [];
const LAYER_RANK = {
  generated: -1,
  entry: 0,
  routes: 1,
  components: 2,
  hooks: 2.5,
  api: 3,
  data: 4,
  lib: 5,
  types: 6,
  other: 3,
};
const expectedDown = new Set([
  "routes→components",
  "routes→api",
  "routes→data",
  "routes→lib",
  "routes→hooks",
  "components→api",
  "components→data",
  "components→lib",
  "components→hooks",
  "components→components",
  "api→data",
  "api→lib",
  "data→lib",
  "hooks→lib",
  "hooks→api",
  "lib→lib",
  "entry→routes",
  "entry→lib",
  "entry→components",
  "generated→routes",
]);
const flagged = [
  "components→routes",
  "api→components",
  "data→components",
  "lib→api",
  "api→data", // wait, api→data is expected. circular would be data→api
  "data→api",
  "lib→components",
  "lib→routes",
  "data→routes",
  "api→routes",
  "hooks→components",
  "hooks→routes",
];

for (const [from, tos] of adj) {
  const lf = layerOf(from);
  for (const to of tos) {
    const lt = layerOf(to);
    const key = `${lf}→${lt}`;
    layerEdges[key] = (layerEdges[key] || 0) + 1;
    const pair = `${from} → ${to}`;
    if (lf === "components" && lt === "routes")
      violations.push({ kind: "components importing routes", pair, from, to });
    if (lf === "api" && lt === "components")
      violations.push({ kind: "api importing components", pair, from, to });
    if (lf === "data" && lt === "components")
      violations.push({ kind: "data importing components", pair, from, to });
    if (lf === "lib" && lt === "api")
      violations.push({ kind: "lib importing api", pair, from, to });
    if (lf === "data" && lt === "api")
      violations.push({ kind: "data importing api (circular api↔data)", pair, from, to });
    if (lf === "lib" && lt === "components")
      violations.push({ kind: "lib importing components", pair, from, to });
    if (lf === "lib" && lt === "routes")
      violations.push({ kind: "lib importing routes", pair, from, to });
    if (lf === "api" && lt === "routes")
      violations.push({ kind: "api importing routes", pair, from, to });
    if (lf === "data" && lt === "routes")
      violations.push({ kind: "data importing routes", pair, from, to });
    if (lf === "hooks" && lt === "routes")
      violations.push({ kind: "hooks importing routes", pair, from, to });
  }
}

// Alias usage
let aliasImports = 0;
let relativeInternal = 0;
for (const abs of files) {
  const text = fs.readFileSync(abs, "utf8");
  const cleaned = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
  const re = /from\s+["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)/g;
  let m;
  while ((m = re.exec(cleaned))) {
    const spec = m[1] || m[2];
    if (spec?.startsWith("@/")) aliasImports++;
    else if (spec?.startsWith(".")) relativeInternal++;
  }
}

// Barrel analysis
const barrels = ["components/charts/index.ts", "components/records/index.ts"];
const barrelInfo = {};
for (const b of barrels) {
  const importers = [...(inbound.get(b) || [])];
  const exportsTo = [...(adj.get(b) || [])];
  barrelInfo[b] = {
    importers: importers.sort(),
    importerCount: importers.length,
    reexports: exportsTo.sort(),
    reexportCount: exportsTo.length,
    inCycle: cycles.some((c) => c.includes(b)),
  };
}

// Who imports barrels vs direct files of those packages
const chartsFiles = [...nodes].filter((n) => n.startsWith("components/charts/") && n !== "components/charts/index.ts");
const recordsFiles = [...nodes].filter((n) => n.startsWith("components/records/") && n !== "components/records/index.ts");
const chartsDirectImporters = new Set();
for (const f of chartsFiles) for (const i of inbound.get(f) || []) if (!i.startsWith("components/charts/")) chartsDirectImporters.add(`${i} → ${f}`);
const recordsDirectImporters = new Set();
for (const f of recordsFiles) for (const i of inbound.get(f) || []) if (!i.startsWith("components/records/")) recordsDirectImporters.add(`${i} → ${f}`);

// Exclude generated from counts for "app graph"
const appNodes = [...nodes].filter((n) => n !== "routeTree.gen.ts");
const appEdges = [...adj.entries()].reduce((acc, [f, tos]) => {
  if (f === "routeTree.gen.ts") return acc;
  for (const t of tos) if (t !== "routeTree.gen.ts") acc++;
  return acc;
}, 0);

const appOrphans = orphans.filter((n) => n !== "routeTree.gen.ts");
const appLeaves = leaves.filter((n) => n !== "routeTree.gen.ts");

// Classify orphans
function classifyOrphan(n) {
  if (n.endsWith(".test.ts") || n.endsWith(".test.tsx")) return "test";
  if (n === "router.tsx" || n === "server.ts" || n === "routes/__root.tsx") return "entry";
  if (n.startsWith("routes/")) return "route-entry";
  if (n.startsWith("types/")) return "ambient-types";
  return "unreferenced";
}

const orphanClass = {};
for (const o of appOrphans) {
  const c = classifyOrphan(o);
  if (!orphanClass[c]) orphanClass[c] = [];
  orphanClass[c].push(o);
}

// High centrality: in * out or betweenness proxy = fan-in
const hubs = fanIn.filter((x) => x.in >= 8).slice(0, 25);

const result = {
  totals: {
    srcTsFiles: files.length,
    nodes: nodes.size,
    appNodes: appNodes.length,
    edges: edgeCount,
    appEdges,
    orphans: orphans.length,
    appOrphans: appOrphans.length,
    leaves: leaves.length,
    appLeaves: appLeaves.length,
    sccs: sccs.length,
    simpleCycles: cycles.length,
    unresolved: unresolved.length,
    aliasImports,
    relativeInternal,
  },
  byDir,
  componentDirs,
  cycles: cycles.map((c) => c.join(" → ")),
  sccs: sccs.map((s) => s.sort()),
  fanInTop20: fanIn.slice(0, 20),
  fanOutTop20: fanOut.slice(0, 20),
  orphans: appOrphans.sort(),
  orphanClass: Object.fromEntries(
    Object.entries(orphanClass).map(([k, v]) => [k, v.sort()]),
  ),
  leavesSample: appLeaves.sort().slice(0, 40),
  leafCount: appLeaves.length,
  layerEdges: Object.fromEntries(Object.entries(layerEdges).sort((a, b) => b[1] - a[1])),
  violations: violations.map((v) => ({ kind: v.kind, from: v.from, to: v.to })),
  violationCounts: violations.reduce((acc, v) => {
    acc[v.kind] = (acc[v.kind] || 0) + 1;
    return acc;
  }, {}),
  barrels: barrelInfo,
  chartsDirectImporters: [...chartsDirectImporters].sort(),
  recordsDirectImporters: [...recordsDirectImporters].sort(),
  unresolved,
  externalTop: [...externalCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20),
  hubs,
};

fs.writeFileSync(
  "D:/Hackathon/artifacts/frontend-static-review/graph-analysis.json",
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result.totals, null, 2));
console.log("byDir", JSON.stringify(byDir, null, 2));
console.log("layerEdges", JSON.stringify(result.layerEdges, null, 2));
console.log("violationCounts", JSON.stringify(result.violationCounts, null, 2));
console.log("fanInTop15", JSON.stringify(result.fanInTop20.slice(0, 15), null, 2));
console.log("fanOutTop15", JSON.stringify(result.fanOutTop20.slice(0, 15), null, 2));
console.log("cycles", result.cycles);
console.log("orphanClass counts", Object.fromEntries(Object.entries(orphanClass).map(([k, v]) => [k, v.length])));
console.log("barrels", JSON.stringify(barrelInfo, null, 2));
console.log("unresolved", unresolved.slice(0, 20));
