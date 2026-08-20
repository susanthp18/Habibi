#!/usr/bin/env node
/**
 * Fail on spacing utilities that the design system does not define.
 *
 * Tailwind v4 has a dynamic spacing scale: any `px-<number>` is valid and means
 * `number x --spacing` (0.25rem by default). That is a silent trap for a token
 * system like this one, whose steps are zero-padded hundredths — `px-100` is
 * 8px, `px-150` is 12px, and there is no `125`. Writing `px-125` does not error
 * and does not fall back; it resolves through Tailwind's own scale to
 * 125 x 0.25rem = **500px** of padding per side.
 *
 * That shipped. Three `px-125` in the flow node card gave every node 1000px of
 * horizontal padding, collapsing its title and instructions to zero width — so
 * the graph rendered as a row of empty boxes, but only when zoomed in far
 * enough to leave the compact layout, which is why it looked like a zoom bug.
 * Four more in the audit call-cost panel had the same 500px vertical padding
 * sitting there unnoticed.
 *
 * Nothing else catches this: it type-checks, it lints, it builds, and the class
 * is real CSS. Only the rendered pixels are wrong.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");
const CSS = join(SRC, "styles.css");

/** Utilities whose numeric argument comes from the spacing scale. */
const PREFIXES = [
  "p", "px", "py", "pt", "pr", "pb", "pl",
  "m", "mx", "my", "mt", "mr", "mb", "ml",
  "gap", "gap-x", "gap-y", "space-x", "space-y",
  "w", "h", "size", "inset", "inset-x", "inset-y",
  "top", "right", "bottom", "left",
];

// Only this system's own convention: three or four digits. Tailwind's stock
// one- and two-digit utilities (`w-64`, `gap-2`) are a separate, valid scale.
const UTILITY_RE = new RegExp(
  String.raw`(?<![\w-])-?(${PREFIXES.join("|")})-(\d{3,4})(?![\w-])`,
  "g",
);

function definedSteps() {
  const css = readFileSync(CSS, "utf8");
  const steps = new Set();
  for (const m of css.matchAll(/--spacing-(\d+)\s*:/g)) steps.add(m[1]);
  if (steps.size === 0) {
    console.error("check-spacing-scale: found no --spacing-* tokens in styles.css");
    process.exit(2);
  }
  return steps;
}

function* sources(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* sources(full);
    else if (/\.(tsx?|jsx?)$/.test(entry)) yield full;
  }
}

const steps = definedSteps();
const bad = [];

for (const file of sources(SRC)) {
  const text = readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    for (const m of line.matchAll(UTILITY_RE)) {
      if (steps.has(m[2])) continue;
      bad.push({ file: relative(ROOT, file), line: i + 1, utility: m[0].trim() });
    }
  });
}

if (bad.length) {
  const known = [...steps].sort((a, b) => Number(a) - Number(b)).join(", ");
  console.error(`\n${bad.length} spacing utility/utilities are not in the design scale:\n`);
  for (const b of bad) console.error(`  ${b.file}:${b.line}  ${b.utility}`);
  console.error(
    `\nDefined steps: ${known}` +
      `\nAn undefined step does NOT fail — Tailwind resolves it as n x 0.25rem, ` +
      `so e.g. px-125 becomes 500px per side. Pick a defined step, or add the ` +
      `token to both --space-* and --spacing-* in src/styles.css.\n`,
  );
  process.exit(1);
}

console.log(`check-spacing-scale: clean (${steps.size} defined steps)`);
