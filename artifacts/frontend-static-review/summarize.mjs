import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const outDir = "D:\\Hackathon\\artifacts\\frontend-static-review";

function loadJson(name) {
  const raw = readFileSync(path.join(outDir, name), "utf8");
  const start = raw.indexOf("{") >= 0 && raw.indexOf("{") < (raw.indexOf("[") === -1 ? Infinity : raw.indexOf("["))
    ? raw.indexOf("{")
    : raw.indexOf("[");
  return JSON.parse(raw.slice(Math.max(0, start)));
}

function bump(map, key, n = 1) {
  map[key] = (map[key] ?? 0) + n;
}

function topEntries(map, n = 30) {
  return Object.entries(map)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([k, v]) => ({ key: k, count: v }));
}

function summarizeOxlint() {
  const data = loadJson("oxlint.json");
  const diagnostics = data.diagnostics ?? [];
  const byCode = {};
  const byFile = {};
  const bySeverity = {};
  const items = diagnostics.map((d) => {
    const file = (d.filename ?? "").replaceAll("\\", "/");
    const code = d.code ?? "unknown";
    const severity = d.severity ?? "unknown";
    const line = d.labels?.[0]?.span?.line ?? null;
    bump(byCode, code);
    bump(byFile, file);
    bump(bySeverity, severity);
    return {
      file,
      line,
      code,
      severity,
      message: d.message,
      help: d.help ?? null,
    };
  });
  return {
    filesScanned: data.number_of_files,
    rules: data.number_of_rules,
    count: diagnostics.length,
    bySeverity,
    byCode: topEntries(byCode, 50),
    byFile: topEntries(byFile, 40),
    items,
  };
}

function summarizeBiome() {
  const data = loadJson("biome.json");
  const diags = data.diagnostics ?? [];
  const byCategory = {};
  const byRule = {};
  const bySeverity = {};
  const byFile = {};
  const lintItems = [];
  const formatCount = { files: 0 };
  for (const d of diags) {
    const cat = d.category ?? "unknown";
    const severity = d.severity ?? "unknown";
    const loc = d.location?.path?.file ?? d.location?.path ?? "";
    const file = String(loc).replaceAll("\\", "/").replace(/^.*\/src\//, "src/");
    bump(byCategory, cat);
    bump(bySeverity, severity);
    bump(byFile, file);
    if (cat === "format" || cat === "assist") {
      if (cat === "format") formatCount.files += 1;
      continue;
    }
    const rule = cat;
    bump(byRule, rule);
    lintItems.push({
      file,
      line: d.location?.span?.[0] ? undefined : d.location?.start?.line,
      span: d.location?.span ?? null,
      category: cat,
      severity,
      message: d.message ?? d.description ?? JSON.stringify(d.message),
    });
  }
  return {
    diagnosticCount: diags.length,
    byCategory: topEntries(byCategory, 80),
    bySeverity,
    byFile: topEntries(byFile, 20),
    lintRuleCounts: topEntries(byRule, 80),
    lintItems: lintItems.slice(0, 400),
    lintItemCount: lintItems.length,
    sample: diags.slice(0, 3),
  };
}

function summarizeKnip() {
  let data;
  try {
    data = loadJson("knip.json");
  } catch {
    return { error: "knip.json not valid JSON yet" };
  }
  const files = data.files ?? [];
  const issues = data.issues ?? data;
  const unusedDeps = data.dependencies ?? [];
  const unusedDevDeps = data.devDependencies ?? [];
  const unlisted = data.unlisted ?? [];
  const unresolved = data.unresolved ?? [];
  const unusedExports = data.exports ?? [];
  const unusedTypes = data.types ?? [];
  const duplicates = data.duplicates ?? [];
  const enumMembers = data.enumMembers ?? [];
  const nsExports = data.nsExports ?? [];
  const nsTypes = data.nsTypes ?? [];
  return {
    keys: Object.keys(data),
    unusedFiles: files,
    unusedDependencies: unusedDeps,
    unusedDevDependencies: unusedDevDeps,
    unlisted,
    unresolved,
    unusedExportsCount: Array.isArray(unusedExports) ? unusedExports.length : unusedExports,
    unusedTypesCount: Array.isArray(unusedTypes) ? unusedTypes.length : unusedTypes,
    unusedExports,
    unusedTypes,
    duplicates,
    enumMembers,
    nsExports,
    nsTypes,
    rawPreview: data,
  };
}

const summary = {
  generatedAt: new Date().toISOString(),
  oxlint: summarizeOxlint(),
  biome: summarizeBiome(),
  knip: summarizeKnip(),
};

writeFileSync(path.join(outDir, "summary.json"), JSON.stringify(summary, null, 2), "utf8");
console.log(
  JSON.stringify(
    {
      oxlintCount: summary.oxlint.count,
      oxlintByCode: summary.oxlint.byCode,
      biomeDiags: summary.biome.diagnosticCount,
      biomeCategories: summary.biome.byCategory.slice(0, 25),
      biomeLintCount: summary.biome.lintItemCount,
      knipKeys: summary.knip.keys ?? summary.knip.error,
    },
    null,
    2,
  ),
);
