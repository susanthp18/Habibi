#!/usr/bin/env node
/**
 * Fail on a test that asserts a component's behaviour by reading its source.
 *
 * `readFileSync(...).toContain("Effective contract")` passes when that string
 * appears anywhere in the file — in a comment, in dead code, in a variable name,
 * in a prop that is never rendered. It is a test of the repository's contents,
 * not of the program's behaviour, and it goes green through exactly the changes
 * a test exists to catch: an early return, a guard, a `hidden` prop, a component
 * that is imported and never mounted.
 *
 * The studio had six of these standing in for its only coverage of six panels.
 * jsdom and @testing-library/react are already installed and
 * `src/test/jsdom.ts` already exists, so the honest version costs a `// @vitest-
 * environment jsdom` line and a render.
 *
 * Reading a `.ts` sibling for a shared constant stays legal — that is a
 * vocabulary check, and it is how the cross-language pins work. Reading a
 * component to assert what it renders is the banned pattern.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");

/**
 * Known violations, with the panel each one stands in for.
 *
 * This list may only ever get shorter. It exists because a gate introduced red
 * is a gate people learn to ignore — the same reasoning `npm audit
 * --audit-level=high` and eslint's warning budget are pinned on in
 * .github/workflows/frontend-typecheck.yml. Delete an entry when its panel gets
 * a real render test; do not add one.
 */
const ALLOWED = new Set([
  "src/lib/studio-contract.test.ts", // 6 assertions standing in for 6 panels
  "src/lib/studio-trust.test.ts", // FlowInspector's ungranted-tool chip
  "src/api/sandbox.test.ts", // sandbox.lazy.tsx promote payload
  "src/routes/agent-studio.skills.index.test.ts", // the clone dialog copy
]);

/** `readFileSync(...)` anywhere near a path that ends in .tsx. */
const READS_A_COMPONENT = /readFileSync\([^)]*\.tsx/;

function testFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...testFiles(full));
    else if (/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const offenders = [];
for (const file of testFiles(SRC)) {
  const rel = relative(ROOT, file).split("\\").join("/");
  if (ALLOWED.has(rel)) continue;
  const text = readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    if (READS_A_COMPONENT.test(line)) {
      offenders.push({ file: rel, line: i + 1, code: line.trim().slice(0, 96) });
    }
  });
}

if (offenders.length) {
  console.error(`\n${offenders.length} test(s) assert a component by reading its source:\n`);
  for (const o of offenders) console.error(`  ${o.file}:${o.line}  ${o.code}`);
  console.error(
    `\nA string match on a .tsx file passes on a comment and survives an early ` +
      `return. Render the component instead — jsdom and @testing-library/react ` +
      `are installed; add "// @vitest-environment jsdom" and ` +
      `import "@/test/jsdom" at the top of the file.\n`,
  );
  process.exit(1);
}

console.log(`check-no-source-grep-tests: clean (${ALLOWED.size} allowed, and that list only shrinks)`);
