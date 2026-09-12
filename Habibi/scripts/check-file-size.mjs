#!/usr/bin/env node
/**
 * No route file over 500 lines, no component or api module over 800; the ones
 * that still are may only shrink.
 *
 * A 1,500-line route is a page with fourteen components and thirty pieces of
 * state that nobody can move without moving all of it. The backend has the
 * same rule for functions (tests/test_function_size.py); this is the frontend
 * twin, on files, because a React file is the unit that gets split.
 *
 * BASELINE lists what was over the ceiling on 2026-09-12 with its measured
 * length. A split lowers the number or removes the entry; nothing may join,
 * and a listed file may not grow. Test files and the generated wire schemas
 * are not measured.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const LIMITS = { "src/routes": 500, "src/components": 800, "src/api": 800 };

/** Measured on 2026-09-12. Shrink or delete; never add. */
const BASELINE = {
  "src/routes/_app.treatment.lazy.tsx": 1499,
  "src/components/flow/FlowCanvas.tsx": 1419,
  "src/routes/_app.prompt-studio.lazy.tsx": 1417,
  "src/components/flow/FlowInspector.tsx": 1123,
  "src/components/prompt-studio/OutboundCardEditor.tsx": 1104,
  "src/components/prompt-studio/VoiceCatalogBrowser.tsx": 1039,
  "src/components/prompt-studio/VoicePanel.tsx": 1019,
  "src/routes/_app.knowledge-base.lazy.tsx": 944,
  "src/components/prompt-studio/OutboundTab.tsx": 807,
  "src/routes/_app.agent-studio.index.tsx": 744,
  "src/routes/_app.sandbox.lazy.tsx": 721,
  "src/routes/_app.handoff.lazy.tsx": 563,
  "src/api/prompt-studio.ts": 838,
  "src/api/agent-studio.ts": 815,
};

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) && name !== "generated.ts")
      yield p;
  }
}

const over = {};
for (const [dir, limit] of Object.entries(LIMITS)) {
  for (const file of walk(join(ROOT, dir))) {
    const lines = readFileSync(file, "utf8").split(/\r?\n/).length;
    if (lines > limit) over[relative(ROOT, file).replace(/\\/g, "/")] = lines;
  }
}

const problems = [];
for (const [file, lines] of Object.entries(over)) {
  if (!(file in BASELINE))
    problems.push(`${file} is ${lines} lines and not in the baseline -- split it`);
  else if (lines > BASELINE[file]) problems.push(`${file} grew: ${BASELINE[file]} -> ${lines}`);
}
for (const [file, lines] of Object.entries(BASELINE)) {
  if (over[file] !== lines)
    problems.push(
      `baseline for ${file} is stale (${lines}; now ${over[file] ?? "under the ceiling"}) -- set it to the measured value or delete it`,
    );
}

if (problems.length) {
  console.error("check-file-size: " + problems.length + " problem(s)\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log(
  `check-file-size: ok (${Object.keys(BASELINE).length} baselined file(s) over the ceiling)`,
);
