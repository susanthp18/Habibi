#!/usr/bin/env node
/**
 * Fail on a dropdown that draws its own chrome.
 *
 * There were two kinds of dropdown in this app and no rule saying which to use.
 * 82 raw `<select>`s across 34 files opened the operating system's menu; 57
 * Radix `<SelectTrigger>`s across 21 files opened a styled popover. Between them
 * they carried **47 distinct className strings** — 29 on the selects, 18 on the
 * triggers — so the same control was 36px on Compliance, 32px on Callbacks, 28px
 * on Documents, 24px on the Documents type filter and 16px on the Outbound card
 * editor, in four background colours and three border colours. Billing, Prompt
 * Studio and Knowledge Base each showed both kinds on one screen.
 *
 * Two things caused it and this check closes both.
 *
 * **There was no primitive for `<select>`.** `flow/inspector/chrome.tsx` said so in
 * a comment — "Matches the system's Input height and chrome; `select` has no
 * primitive" — and hand-rolled one anyway; `prompt-studio/outbound/` (then one file)
 * hand-rolled a second, 16px one. `SelectField` in `ui/select.tsx` is the
 * primitive that was missing.
 *
 * **The size tier had no name.** Button names its sizes (`default`/`compact`);
 * Input and SelectTrigger did not, so 29 Input call sites wrote `h-400
 * text-body-small` by hand to get the dense look, and the selects beside them
 * wrote their own. When one was updated and the other was not you got a 36px
 * Input against a 32px select — which is what a filter bar looked like.
 *
 * Nothing else catches this: every one of those strings type-checks, lints,
 * builds, and renders. Only the pixels disagree. Sibling of
 * check-spacing-scale.mjs and check-type-scale.mjs, which guard the two halves
 * of the design system this one sits on top of.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { isVendored } from "./vendored.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");

/**
 * Known exceptions, each with the reason it is not a dropdown wearing a costume.
 *
 * This list may only ever get shorter — same rule as check-no-source-grep-tests
 * and check-file-size. A gate introduced red is a gate people learn to ignore.
 */
const ALLOWED = new Map([]);

/** Chrome: what the primitive owns. Anything here belongs in `size`, not here. */
const CHROME = [
  [/(?<![\w-])h-(?:\d{1,4}|px|full|auto|screen)(?![\w-])/, "height — use size"],
  [/(?<![\w-])bg-[\w-]+(?![\w-])/, "background"],
  [/(?<![\w-])border(?:-[\w-]+)?(?![\w-])/, "border"],
  [/(?<![\w-])text-(?:body[\w-]*|sm|xs|base|lg)(?![\w-])/, "type scale — use size"],
  [/(?<![\w-])shadow-[\w-]+(?![\w-])/, "shadow"],
];

/**
 * Layout is the call site's business and stays legal: how wide the control is,
 * where it sits, and the left inset a search icon needs. Only the look of the
 * control itself is owned by the primitive.
 */

const CONTROLS = ["SelectTrigger", "SelectField", "Input"];

function* sources(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (isVendored(full)) continue;
    if (statSync(full).isDirectory()) yield* sources(full);
    else if (/\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry)) yield full;
  }
}

/**
 * The index of the `>` closing a JSX tag whose attributes start at `i`.
 *
 * A plain `[^>]*` does not work here: half these call sites have an arrow
 * function in `onChange`, and `=>` contains the character being searched for.
 */
function tagEnd(text, i) {
  let depth = 0;
  let quote = null;
  for (; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      if (c === quote && text[i - 1] !== "\\") quote = null;
    } else if (c === '"' || c === "'" || c === "`") quote = c;
    else if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0) return i;
  }
  return text.length;
}

/**
 * Comments quote class names constantly here, and none of them renders.
 *
 * This walks the source instead of running two regexes over it, because the
 * regex version eats `https://bank.example/mcp` in ConnectorsPanel's placeholder —
 * and once half a string literal is gone, every tag boundary after it is wrong.
 * The check reported a `border` class on an `<Input>` that has no className.
 */
function stripComments(text) {
  let out = "";
  let quote = null;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      out += c;
      if (c === quote && text[i - 1] !== "\\") quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      quote = c;
      out += c;
      continue;
    }
    if (c === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      out += "\n";
      continue;
    }
    if (c === "/" && text[i + 1] === "*") {
      const end = text.indexOf("*/", i + 2);
      const block = text.slice(i, end < 0 ? text.length : end + 2);
      out += block.replace(/[^\n]/g, " ");
      i += block.length - 1;
      continue;
    }
    out += c;
  }
  return out;
}

const natives = [];
const chromed = [];
const staleAllowances = new Set(ALLOWED.keys());

for (const file of sources(SRC)) {
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  if (rel === "src/components/ui/select.tsx" || rel === "src/components/ui/input.tsx") continue;
  const text = stripComments(readFileSync(file, "utf8"));

  for (const m of text.matchAll(/<select(?![\w-])/g)) {
    natives.push({ file: rel, line: text.slice(0, m.index).split("\n").length });
  }

  if (ALLOWED.has(rel)) {
    staleAllowances.delete(rel);
    continue;
  }

  for (const control of CONTROLS) {
    const open = new RegExp(`<${control}(?![\\w-])`, "g");
    for (const m of text.matchAll(open)) {
      const start = m.index + m[0].length;
      const attrs = text.slice(start, tagEnd(text, start));
      const cls = /className="([^"]*)"/.exec(attrs);
      if (!cls) continue;
      for (const [re, what] of CHROME) {
        const hit = re.exec(cls[1]);
        if (!hit) continue;
        chromed.push({
          file: rel,
          line: text.slice(0, m.index).split("\n").length,
          control,
          utility: hit[0],
          what,
        });
      }
    }
  }
}

const problems = [];

if (natives.length) {
  console.error(`\n${natives.length} raw <select> element(s):\n`);
  for (const b of natives) console.error(`  ${b.file}:${b.line}`);
  console.error(
    `\nA native select opens the operating system's menu — no chevron, no ` +
      `hover, no focus ring, and nothing the design system can style. Use ` +
      `<SelectField> from @/components/ui/select. A control that toggles ` +
      `several values, or fires an action and resets, is a DropdownMenu ` +
      `instead: it never was a select.\n`,
  );
  problems.push("native select");
}

if (chromed.length) {
  console.error(`\n${chromed.length} dropdown/input className(s) redrawing the chrome:\n`);
  for (const b of chromed) {
    console.error(
      `  ${b.file}:${b.line}  <${b.control} className="… ${b.utility} …">  (${b.what})`,
    );
  }
  console.error(
    `\nHeight, background, border, shadow and type belong to the primitive, ` +
      `which names exactly two of them: size="default" (h-9, text-body) and ` +
      `size="compact" (h-400, text-body-small, for dense surfaces only). ` +
      `Width, flex, grid placement, margins and the pl-* a search icon needs ` +
      `stay legal on className.\n`,
  );
  problems.push("hand-drawn chrome");
}

if (staleAllowances.size) {
  console.error(`\nstale entries in ALLOWED — delete them:\n`);
  for (const f of staleAllowances) console.error(`  ${f}`);
  problems.push("stale allowance");
}

if (problems.length) process.exit(1);
console.log(`check-dropdown-chrome: one dropdown, two sizes, everywhere.`);
