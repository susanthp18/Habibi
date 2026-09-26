#!/usr/bin/env node
/**
 * Two repository rules that were being enforced by tests reading source files.
 *
 * A test that does `expect(src).not.toMatch(/\bfetch\s*\(/)` is a lint wearing a
 * test's clothes: it says nothing about behaviour, it only holds for the one
 * file somebody remembered to name, and it goes red in a diff viewer rather
 * than at the place the rule is broken. Both rules below came out of
 * `studio-trust.test.ts` / `sandbox.test.ts` for that reason.
 *
 * **Transport belongs in `src/api/`.** A route or component that calls `fetch`
 * directly bypasses the auth header, the tenant header, the error mapping and
 * the retry policy that every `api/` helper applies — and does it invisibly,
 * because the happy path looks identical until a token expires.
 *
 * **No `window.prompt` / `confirm` / `alert`.** They are unstyleable, they are
 * blocked outright in some embedded browsers, and they cannot show a pending
 * state — so a slow clone looks like a dead click. The repo has AlertDialog.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { isVendored } from "./vendored.mjs";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");

/** `fetch(` / `API_BASE_URL` outside `src/api/` — transport in a view. */
const RAW_TRANSPORT = /(^|[^.\w])fetch\s*\(|API_BASE_URL/;

/** Browser modals. `window.` prefixed or bare. */
const BROWSER_MODAL = /(^|[^.\w])(window\s*\.\s*)?(prompt|confirm|alert)\s*\(/;

/**
 * `confirm(` and `alert(` are common enough as local identifiers that a bare
 * match is noisy; only these directories are checked for modals, a file that
 * imports `useConfirm` is calling its own `confirm`, and an
 * `// eslint-disable`-style escape is deliberately not offered — the rule has
 * no legitimate exception in this app.
 */
const OWN_CONFIRM = /from "@\/components\/ui\/use-confirm"/;
const VIEW_DIRS = ["routes", "components"];

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    if (isVendored(full)) continue;
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

/** Strip comments and string literals so a rule name in prose is not a hit. */
function code(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1")
    .replace(/`(?:\\[\s\S]|[^\\`])*`/g, "``")
    .replace(/"(?:\\.|[^"\\])*"/g, '""')
    .replace(/'(?:\\.|[^'\\])*'/g, "''");
}

const problems = [];
for (const file of walk(SRC)) {
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  const raw = readFileSync(file, "utf8");
  const body = code(raw);
  const inApi = rel.startsWith("src/api/");
  const inView = VIEW_DIRS.some((d) => rel.startsWith(`src/${d}/`));

  if (!inApi && inView && RAW_TRANSPORT.test(body)) {
    problems.push(`${rel}: calls fetch()/API_BASE_URL directly — put the request in src/api/`);
  }
  const modal = OWN_CONFIRM.test(raw)
    ? /(^|[^.\w])window\s*\.\s*(prompt|confirm|alert)\s*\(/
    : BROWSER_MODAL;
  if (inView && modal.test(body)) {
    problems.push(`${rel}: uses a browser modal — use AlertDialog, which can show a pending state`);
  }
}

if (problems.length) {
  console.error("check-layering: found violations\n");
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log("check-layering: clean");
