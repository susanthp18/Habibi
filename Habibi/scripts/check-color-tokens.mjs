/**
 * Every colour utility that names a design token must name one that exists.
 *
 * Tailwind v4 emits nothing for `bg-text-muted` or `ring-border-border-warning`
 * -- there is no such `--color-*` -- and says nothing either, so the class sits
 * in the markup painting nothing while reading as if it did. The token
 * namespaces (`background-`, `text-`, `border-`, `surface`, `icon-`, `link`,
 * `chart-`, ...) come from `@theme inline` in styles.css; a utility whose
 * colour argument starts with one of them is checked against the set.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { isVendored } from "./vendored.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(ROOT, "src");

const css = readFileSync(join(SRC, "styles.css"), "utf8");
const TOKENS = new Set([...css.matchAll(/^\s*--color-([a-z0-9-]+)\s*:/gm)].map((m) => m[1]));
if (TOKENS.size < 100) throw new Error(`check-color-tokens: only ${TOKENS.size} tokens parsed`);

/** The first segment of every token: `background`, `text`, `border`, `surface`, ... */
const NAMESPACES = new Set([...TOKENS].map((t) => t.split("-")[0]));
/** Utilities that take a colour argument. */
const UTILITIES =
  "bg|text|border|border-[trblxy]|ring|ring-offset|outline|fill|stroke|divide|decoration|placeholder|shadow|from|via|to|accent|caret";
const CLASS = new RegExp(
  `(?<![\\w-])(?:[a-z-]+:)*(?:${UTILITIES})-((?:${[...NAMESPACES].join("|")})(?:-[a-z0-9]+)*)(?:/\\d+)?(?![\\w-])`,
  "g",
);

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    if (isVendored(full)) continue;
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

const problems = [];
for (const file of walk(SRC)) {
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  const text = readFileSync(file, "utf8");
  for (const m of text.matchAll(CLASS)) {
    const token = m[1];
    if (TOKENS.has(token)) continue;
    // `text-text` is a token; `text-body-small` is the type scale, not a colour.
    if (token.startsWith("text-body") || token.startsWith("text-heading")) continue;
    const line = text.slice(0, m.index).split("\n").length;
    problems.push(`${rel}:${line}: ${m[0]} names no --color-${token}`);
  }
}

if (problems.length) {
  console.error(
    `check-color-tokens: ${problems.length} class(es) name a colour token that does not exist\n`,
  );
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log(`check-color-tokens: ok (${TOKENS.size} tokens)`);
