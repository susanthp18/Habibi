import { readFileSync, writeFileSync } from "node:fs";

const knip = JSON.parse(
  readFileSync("D:/Hackathon/artifacts/frontend-static-review/knip.json", "utf8"),
);
const oxlint = JSON.parse(
  readFileSync("D:/Hackathon/artifacts/frontend-static-review/oxlint.json", "utf8"),
);
const biome = JSON.parse(
  readFileSync("D:/Hackathon/artifacts/frontend-static-review/biome.json", "utf8"),
);

const unusedFiles = [];
const unusedDeps = [];
const unusedExports = [];
const unusedTypes = [];

for (const issue of knip.issues ?? []) {
  for (const f of issue.files ?? []) unusedFiles.push(f.name ?? f);
  for (const d of issue.dependencies ?? []) unusedDeps.push(d.name ?? d);
  for (const d of issue.devDependencies ?? []) unusedDeps.push(`dev:${d.name ?? d}`);
  for (const e of issue.exports ?? []) unusedExports.push({ file: issue.file, name: e.name, line: e.line });
  for (const t of issue.types ?? []) unusedTypes.push({ file: issue.file, name: t.name, line: t.line });
}

const oxByCode = {};
for (const d of oxlint.diagnostics ?? []) {
  oxByCode[d.code] = (oxByCode[d.code] ?? 0) + 1;
}

const biomeByCat = {};
for (const d of biome.diagnostics ?? []) {
  const cat = d.category ?? "unknown";
  biomeByCat[cat] = (biomeByCat[cat] ?? 0) + 1;
}

const biomeLint = Object.entries(biomeByCat)
  .filter(([k]) => k.startsWith("lint/"))
  .sort((a, b) => b[1] - a[1]);

const summary = {
  tsc: { errors: 0, notes: "tsc --noEmit exit 0, empty output. TypeScript 5.8.3 local." },
  knip: {
    unusedFiles: unusedFiles.length,
    unusedDependencies: unusedDeps.length,
    unusedExports: unusedExports.length,
    unusedTypes: unusedTypes.length,
    unusedFilesList: unusedFiles,
    unusedDepsList: unusedDeps,
    unusedExports,
    unusedTypes,
  },
  oxlint: {
    count: (oxlint.diagnostics ?? []).length,
    filesScanned: oxlint.number_of_files,
    rules: oxlint.number_of_rules,
    byCode: oxByCode,
    items: (oxlint.diagnostics ?? []).map((d) => ({
      file: d.filename,
      line: d.labels?.[0]?.span?.line,
      code: d.code,
      message: d.message,
    })),
  },
  biome: {
    total: (biome.diagnostics ?? []).length,
    errors: biome.summary?.errors,
    warnings: biome.summary?.warnings,
    infos: biome.summary?.infos,
    format: biomeByCat.format ?? 0,
    organizeImports: biomeByCat["assist/source/organizeImports"] ?? 0,
    parse: biomeByCat.parse ?? 0,
    lint: biomeLint.reduce((s, [, n]) => s + n, 0),
    lintByRule: Object.fromEntries(biomeLint),
  },
};

writeFileSync(
  "D:/Hackathon/artifacts/frontend-static-review/summary.json",
  JSON.stringify(summary, null, 2),
  "utf8",
);

console.log(
  JSON.stringify(
    {
      knipFiles: unusedFiles.length,
      knipDeps: unusedDeps.length,
      knipExports: unusedExports.length,
      knipTypes: unusedTypes.length,
      oxlint: (oxlint.diagnostics ?? []).length,
      oxByCode,
      biomeTotal: (biome.diagnostics ?? []).length,
      biomeLint: summary.biome.lint,
      biomeFormat: summary.biome.format,
      biomeOrganize: summary.biome.organizeImports,
      biomeParse: summary.biome.parse,
    },
    null,
    2,
  ),
);
