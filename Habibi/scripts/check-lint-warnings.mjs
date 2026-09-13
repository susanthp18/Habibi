/**
 * The type-aware ESLint rules (typescript-eslint recommendedTypeChecked) are
 * errors under src/api and src/lib, where the code parses the wire, and
 * warnings under src/components and src/routes. A warning nobody counts is a
 * warning nobody fixes, so this holds the total and lets it only fall.
 *
 *   npm run lint            (runs this after eslint)
 *   node scripts/check-lint-warnings.mjs --update   (after a real fix)
 */
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Measured 2026-09-13 when the type-aware rules landed. Only falls. */
const BASELINE = 167;

let report;
try {
  report = execFileSync("npx", ["eslint", "src", "-f", "json"], {
    cwd: ROOT,
    encoding: "utf8",
    shell: process.platform === "win32",
    maxBuffer: 64 * 1024 * 1024,
  });
} catch (err) {
  // eslint exits 1 on errors; the JSON is still on stdout.
  report = err.stdout;
}
const files = JSON.parse(report);
const byRule = new Map();
let warnings = 0;
for (const file of files) {
  for (const m of file.messages) {
    if (m.severity !== 1) continue;
    warnings += 1;
    byRule.set(m.ruleId, (byRule.get(m.ruleId) ?? 0) + 1);
  }
}

if (warnings > BASELINE) {
  console.error(
    `check-lint-warnings: ${warnings} warnings (baseline ${BASELINE}); fix the new ones:`,
  );
  for (const [rule, n] of [...byRule].sort((a, b) => b[1] - a[1])) console.error(`  ${n}\t${rule}`);
  process.exit(1);
}
if (warnings < BASELINE) {
  console.log(
    `check-lint-warnings: ${warnings} warnings, below baseline ${BASELINE} -- lower BASELINE in scripts/check-lint-warnings.mjs`,
  );
  process.exit(1);
}
console.log(`check-lint-warnings: ${warnings} warnings (baseline ${BASELINE})`);
