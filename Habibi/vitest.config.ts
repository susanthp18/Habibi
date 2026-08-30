// -----------------------------------------------------------------------------
// Vitest — deliberately separate from vite.config.ts.
//
// vite.config.ts does not call Vite's own defineConfig: it calls the wrapper in
// @lovable.dev/vite-tanstack-config, which composes TanStack devtools,
// tanstackStart, viteReact, tailwind, tsConfigPaths and nitro for us. Its header
// warns that re-adding any of those by hand breaks the app, and a `test` block
// bolted onto that wrapper is neither typed nor guaranteed to survive it. A
// standalone config costs one file and touches none of the app's build.
//
// tsconfigPaths is the one piece that has to be repeated, because the modules
// under test import through the "@/…" alias and nothing else here resolves it.
// Vite 8 does it natively, so no plugin is needed.
// -----------------------------------------------------------------------------

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { tsconfigPaths: true },
  test: {
    // Every suite here exercises a pure function. No jsdom, no DOM shims, no
    // coverage — a test environment the tests do not use is a dependency that
    // can only break.
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
