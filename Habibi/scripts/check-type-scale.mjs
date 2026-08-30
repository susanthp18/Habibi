#!/usr/bin/env node
/**
 * Fail on arbitrary font sizes — `text-[13px]`, `text-[0.65rem]` and friends.
 *
 * Tailwind's arbitrary-value syntax accepts any length, so a one-off font size
 * type-checks, lints, builds, and renders. Nothing catches it, and each one is
 * invisible on its own. In aggregate they were the whole type system: 169 sites
 * across 60 files using 18 distinct sizes — 8.8, 9.6, 10, 10.4, 10.5, 11, 11.2,
 * 11.5, 12, 12.5, 12.8, 13, 14, 16, 16.8, 20, 21.6 and 24 pixels.
 *
 * Half of those pairs are indistinguishable on a screen (10.4 vs 10.5, 11.2 vs
 * 11.5, 12.5 vs 12.8), so they bought nothing. What they cost is the ability to
 * change typography at all: "make all the helper text a step larger" had no
 * single place to happen, and any answer to "what size is this?" was a
 * different number in every file.
 *
 * The scale itself was the cause — it stopped at 0.75rem and the app did not,
 * so every piece of micro-copy had to invent one. `text-body-tiny` and
 * `text-body-micro` close that gap; this check keeps it closed.
 *
 * Sibling of check-spacing-scale.mjs, which guards the other half of the
 * design system for the same reason.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");
const CSS = join(SRC, "styles.css");

/** `text-[…]` carrying a length. `text-[--var]` and colours are not sizes. */
const ARBITRARY_RE = /(?<![\w-])text-\[\s*[0-9.]+(px|rem|em|pt|%)\s*\]/g;

/** Any `text-foo` word class, so undefined ones can be caught too. */
const NAMED_RE = /(?<![\w-])text-([a-z][a-z0-9-]*)(?:\/\d+)?(?![\w[-])/g;

/**
 * Tailwind's own `text-*` utilities, which are real CSS without a token here.
 *
 * Sizes are included because they exist and work; the scale check that matters
 * is the arbitrary-value one above, and a project that wants to ban `text-sm`
 * outright should say so separately rather than have this check fail on a class
 * that does render.
 */
const TAILWIND_TEXT = new Set([
  "left",
  "center",
  "right",
  "justify",
  "start",
  "end",
  "wrap",
  "nowrap",
  "balance",
  "pretty",
  "ellipsis",
  "clip",
  "transparent",
  "current",
  "inherit",
  "white",
  "black",
  "xs",
  "sm",
  "base",
  "lg",
  "xl",
  "2xl",
  "3xl",
  "4xl",
  "5xl",
  "6xl",
  "7xl",
  "8xl",
  "9xl",
  "shadow",
]);

/** Tailwind's stock palette, e.g. `text-teal-700`. Shipped unless opted out. */
const TAILWIND_PALETTE =
  /^(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(50|\d{3})$/;

/**
 * Does this string literal read as a list of classes?
 *
 * Without this the scan flags `"text-embedding-3-small"` in the KB seed and
 * `"text-to-speech"` in the integrations seed — real strings that merely start
 * with the same five characters. A class list has other classes in it; a model
 * id does not.
 */
const UTILITY_TOKEN =
  /(?:^|\s)(?:flex|grid|block|inline|hidden|absolute|relative|fixed|sticky|truncate|tabular-nums|italic|uppercase|lowercase|capitalize|underline|shrink|grow|isolate|(?:rounded|border|bg|font|leading|tracking|opacity|shadow|ring|cursor|select|z|top|left|right|bottom|inset|gap|space|overflow|whitespace|line-clamp|animate|transition|min|max|size|w|h|p[xytrbl]?|m[xytrbl]?|items|justify|self|place|col|row|order|basis|divide|outline|ml|mr|mt|mb)-)/;

function looksLikeClassList(literal) {
  return UTILITY_TOKEN.test(literal);
}

/**
 * Source with comments removed.
 *
 * Comments in this codebase quote class names constantly — Design.md rules,
 * bug write-ups naming the CSS property that failed — and none of them renders
 * anything. Flagging them would bury the four real ones in forty false ones,
 * which is how a check stops being read.
 */
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/\/\/[^\n]*/g, "");
}

/** The `@utility` names in styles.css that set a font-size. */
function definedTokens() {
  const css = readFileSync(CSS, "utf8");
  const tokens = new Map();
  for (const m of css.matchAll(/@utility\s+([\w-]+)\s*\{([^}]*)\}/g)) {
    const size = /font-size:\s*([^;]+);/.exec(m[2]);
    if (size) tokens.set(m[1], size[1].trim());
  }
  if (tokens.size === 0) {
    console.error("check-type-scale: found no font-size @utility tokens in styles.css");
    process.exit(2);
  }
  return tokens;
}

/**
 * Every `text-foo` this project can actually render: the `@utility` names, plus
 * the colour tokens `@theme` publishes as `--color-*`.
 *
 * Both halves are needed because `text-` is two namespaces wearing one prefix —
 * `text-body-small` is a size and `text-text-subtle` is a colour — and a class
 * in neither produces no CSS at all rather than an error.
 */
function renderableTextClasses() {
  const css = readFileSync(CSS, "utf8");
  const names = new Set();
  for (const m of css.matchAll(/@utility\s+([\w-]+)/g)) {
    if (m[1].startsWith("text-")) names.add(m[1].slice(5));
  }
  for (const m of css.matchAll(/--color-([\w-]+)\s*:/g)) names.add(m[1]);
  return names;
}

function* sources(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* sources(full);
    else if (/\.(tsx?|jsx?)$/.test(entry)) yield full;
  }
}

const tokens = definedTokens();
const renderable = renderableTextClasses();
const bad = [];
const undefinedClasses = [];

/** String literals on a line, so the scan sees class lists and not prose. */
const STRING_RE = /"([^"\n]*)"|'([^'\n]*)'|`([^`\n]*)`/g;

for (const file of sources(SRC)) {
  const text = stripComments(readFileSync(file, "utf8"));
  text.split("\n").forEach((line, i) => {
    for (const m of line.matchAll(ARBITRARY_RE)) {
      bad.push({ file: relative(ROOT, file), line: i + 1, utility: m[0] });
    }
    for (const s of line.matchAll(STRING_RE)) {
      const literal = s[1] ?? s[2] ?? s[3] ?? "";
      if (!looksLikeClassList(literal)) continue;
      for (const m of literal.matchAll(NAMED_RE)) {
        if (TAILWIND_TEXT.has(m[1]) || TAILWIND_PALETTE.test(m[1]) || renderable.has(m[1])) {
          continue;
        }
        undefinedClasses.push({ file: relative(ROOT, file), line: i + 1, utility: m[0] });
      }
    }
  });
}

if (undefinedClasses.length) {
  console.error(
    `\n${undefinedClasses.length} text-* class(es) that no rule defines — ` +
      `they render as nothing at all:\n`,
  );
  for (const b of undefinedClasses) console.error(`  ${b.file}:${b.line}  ${b.utility}`);
  console.error(
    `\nThe quietest failure in the system: the class is valid markup, Tailwind ` +
      `emits no rule for it, and the element silently inherits whatever its ` +
      `parent had. "text-caption" shipped in 80 places this way, across 13 ` +
      `files, rendering at anything from 12px to 16px depending on where it ` +
      `sat. Use a defined token, or add the utility to src/styles.css.\n`,
  );
  process.exit(1);
}

if (bad.length) {
  const known = [...tokens.entries()]
    .sort((a, b) => parseFloat(b[1]) - parseFloat(a[1]))
    .map(([name, size]) => `${name} (${size})`)
    .join("\n  ");
  console.error(`\n${bad.length} arbitrary font size(s) — use a type-scale token:\n`);
  for (const b of bad) console.error(`  ${b.file}:${b.line}  ${b.utility}`);
  console.error(
    `\nDefined tokens:\n  ${known}\n\n` +
      `Each bundles size + weight + line-height and is meant to stay bundled. ` +
      `If none of them fits, add a step to src/styles.css rather than a one-off ` +
      `here — that is how the scale came to have eighteen sizes.\n`,
  );
  process.exit(1);
}

console.log(`check-type-scale: clean (${tokens.size} defined tokens)`);
