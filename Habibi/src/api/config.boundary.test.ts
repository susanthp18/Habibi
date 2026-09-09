// -----------------------------------------------------------------------------
// WP-049: USE_MOCK is a transport switch, not a presentation-layer conditional.
// Screens that asked "are we mocked?" when the real question was "did /staff
// return rows?" rendered an empty assignee dropdown against a live empty roster.
// vitest is environment: "node" — pin the source the way WP-047/WP-050 do.
// -----------------------------------------------------------------------------

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

// `withFileTypes` rather than a `statSync` per entry. The stat call is the whole
// cost of this walk — one syscall per file across components/ and routes/ — and
// on a Windows or bind-mounted filesystem it pushed the test past vitest's 5s
// default and failed it on a timeout, which reads as "USE_MOCK leaked" when
// nothing had. readdir already knows what each entry is.
function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const name = entry.name;
    if (name.endsWith(".test.ts") || name.endsWith(".test.tsx")) continue;
    const full = join(dir, name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (name.endsWith(".ts") || name.endsWith(".tsx")) out.push(full);
  }
  return out;
}

describe("USE_MOCK stays in api/", () => {
  // 30s, not vitest's 5s default. This reads every .ts/.tsx under components/
  // and routes/ — several hundred files — and on a bind-mounted or Windows
  // filesystem that alone exceeds the default, failing the test on a timeout
  // that reads as "USE_MOCK leaked" when nothing has. It is a source scan, not
  // a latency assertion; there is nothing here for a timeout to protect.
  it("is not imported from components/ or routes/", { timeout: 30_000 }, () => {
    const hits: string[] = [];
    for (const dir of ["components", "routes"]) {
      for (const file of walk(join(srcRoot, dir))) {
        const src = readFileSync(file, "utf8");
        if (/\bUSE_MOCK\b/.test(src)) hits.push(relative(srcRoot, file).replace(/\\/g, "/"));
      }
    }
    expect(hits).toEqual([]);
  });
});
