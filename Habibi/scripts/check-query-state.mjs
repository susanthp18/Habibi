/**
 * `query.data ?? []` in a file that never looks at `isError` renders a failed
 * read as an empty list -- "no connectors", "no reports" -- which is a statement
 * about the system made from a network error. ui/query-state.tsx is the way
 * to say the three things apart; a file that imports it, or that passes
 * `isError` to a table, is trusted to. The rest are counted here, and the
 * count only falls.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(ROOT, "src");

/** Zero since 2026-09-13: every failed read says so. Stays zero. */
const BASELINE = 0;

const FALLBACK = /\.data \?\? \[\]/g;
const GUARDED = /components\/ui\/query-state"|\bisError\b/;

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const sites = [];
for (const file of walk(SRC)) {
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  if (rel === "src/components/ui/query-state.tsx") continue;
  const text = readFileSync(file, "utf8");
  if (GUARDED.test(text)) continue;
  for (const m of text.matchAll(FALLBACK)) {
    sites.push(`${rel}:${text.slice(0, m.index).split("\n").length}`);
  }
}

if (sites.length > BASELINE) {
  console.error(
    `check-query-state: ${sites.length} unguarded \`.data ?? []\` site(s), baseline ${BASELINE} -- route the read through QueryState (or pass isError to the table) instead of adding one\n`,
  );
  for (const s of sites) console.error(`  ${s}`);
  process.exit(1);
}
if (sites.length < BASELINE) {
  console.error(
    `check-query-state: ${sites.length} site(s) now, baseline ${BASELINE} -- lower BASELINE in scripts/check-query-state.mjs to keep the ratchet`,
  );
  process.exit(1);
}
console.log(`check-query-state: ok (${sites.length} unguarded site(s), at the baseline)`);
