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

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SRC = join(ROOT, "src");

/** `fetch(` / `API_BASE_URL` outside `src/api/` — transport in a view. */
const RAW_TRANSPORT = /(^|[^.\w])fetch\s*\(|API_BASE_URL/;

/** Browser modals. `window.` prefixed or bare. */
const BROWSER_MODAL = /(^|[^.\w])(window\s*\.\s*)?(prompt|confirm|alert)\s*\(/;

/**
 * `confirm(` and `alert(` are common enough as local identifiers that a bare
 * match is noisy; only these directories are checked for modals, and a
 * `// eslint-disable`-style escape is deliberately not offered — the rule has
 * no legitimate exception in this app.
 */
const VIEW_DIRS = ["routes", "components"];

/**
 * Modal violations that predate this rule. Shrink-only, same reasoning as
 * `check-no-source-grep-tests.mjs`: a gate introduced red is a gate people
 * learn to ignore, so the four that exist are named and the fifth cannot be
 * added. Each is a `window.confirm` guarding a destructive action, which is the
 * case AlertDialog exists for — they are worth converting, but not in the same
 * change that introduces the rule.
 */
const ALLOWED_MODALS = new Set([
  "src/components/billing/BudgetPanel.tsx",
  "src/components/platform/OutboundControlPanel.tsx",
  "src/routes/_app.inbox.tsx",
  "src/routes/_app.webhooks.tsx",
]);

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
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
  const body = code(readFileSync(file, "utf8"));
  const inApi = rel.startsWith("src/api/");
  const inView = VIEW_DIRS.some((d) => rel.startsWith(`src/${d}/`));

  if (!inApi && inView && RAW_TRANSPORT.test(body)) {
    problems.push(`${rel}: calls fetch()/API_BASE_URL directly — put the request in src/api/`);
  }
  if (inView && !ALLOWED_MODALS.has(rel) && BROWSER_MODAL.test(body)) {
    problems.push(`${rel}: uses a browser modal — use AlertDialog, which can show a pending state`);
  }
}

if (problems.length) {
  console.error("check-layering: found violations\n");
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log("check-layering: clean");
