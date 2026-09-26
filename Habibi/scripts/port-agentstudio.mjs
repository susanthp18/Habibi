#!/usr/bin/env node
/**
 * Port the AgentStudio engine's UI (agentstudio/engine/ui/src, Next.js) into
 * Habibi as plain React under src/agentstudio/. Re-run after bumping the
 * engine; never hand-edit src/agentstudio/ — change the rules below or the
 * host code in src/agentstudio-host/ instead.
 *
 *   node scripts/port-agentstudio.mjs
 *
 * What it does, mechanically:
 *   - copies the kept source tree (DROP lists what is not ported: the vendor's
 *     own logins, billing/credits, lead forms, telemetry, superadmin);
 *   - rewrites imports: Next.js modules and dropped vendor widgets resolve to
 *     shims in src/agentstudio-host/, "@/host/<Slot>" (a PayInt extension
 *     point written into the engine UI source) resolves to
 *     src/agentstudio-host/<Slot>, and "@/x" becomes "@/agentstudio/x";
 *   - applies the white-label text rules (REWORD) and theme class rules
 *     (CLASSES) so the screens speak AgentStudio and use Habibi's tokens.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { portDocs } from "./agentstudio-docs.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const HABIBI = path.resolve(here, "..");
const SRC = path.resolve(HABIBI, "../agentstudio/engine/ui/src");
const DEST = path.join(HABIBI, "src/agentstudio");
const HOST = "@/agentstudio-host";

/** Paths (relative to SRC, posix) that are not ported. Prefix match. */
const DROP = [
  "middleware.ts",
  "instrumentation.ts",
  "instrumentation-client.ts",
  "app/api/",
  "app/auth/",
  "app/handler/",
  "app/superadmin/",
  "app/impersonate/",
  "app/after-sign-in/",
  "app/billing/",
  "app/overview/",
  "app/automation/",
  "app/layout.tsx",
  "app/page.tsx",
  "app/loading.tsx",
  "app/global-error.tsx",
  "app/globals.css",
  "app/favicon.ico",
  "app/workflow/page.tsx", // server component; host renders the list client-side
  "components/lead-forms/",
  "components/layout/",
  "components/ui/sidebar.tsx", // host: shims/sidebar (the shell owns the sidebar)
  "components/auth/",
  "components/ChatwootWidget.tsx",
  "components/MetaPixel.tsx",
  "components/ReoProvider.tsx",
  "components/PostHogIdentify.tsx",
  "components/EventBanner.tsx",
  "components/SentryErrorBoundary.tsx",
  "components/SignInClient.tsx",
  "components/Footer.tsx",
  "components/ThemeProvider.tsx",
  "components/ThemeSwitcher.tsx",
  "components/GitHubStarBadge.tsx",
  "components/BrandLogo.tsx", // vendor logos; AgentStudio uses the shell's brand
  "context/LeadFormsContext.tsx",
  "context/AppConfigContext.tsx", // host: @/agentstudio-host/app-config
  "lib/apiClient.ts", // host: @/agentstudio-host/api-client
  "lib/auth/",
  "lib/metaPixel.ts",
  "hooks/useLatestReleaseVersion.ts",
  "config/event-banner.config.ts",
];

/** Module specifiers resolved to host code instead of the engine's. */
const REDIRECT = {
  "next/navigation": `${HOST}/shims/next-navigation`,
  "next/link": `${HOST}/shims/next-link`,
  "next-themes": `${HOST}/shims/next-themes`,
  "posthog-js": `${HOST}/shims/posthog`,
  "@/lib/auth": `${HOST}/auth`,
  "@/lib/whitelabel": `${HOST}/whitelabel`,
  "@/lib/signalingUrl": `${HOST}/signaling-url`,
  "@/lib/apiClient": `${HOST}/api-client`,
  "@/context/AppConfigContext": `${HOST}/app-config`,
  "@/components/lead-forms/HireExpertNudge": `${HOST}/shims/nothing`,
  "@/components/layout/GitHubStarBadge": `${HOST}/shims/nothing`,
  "@/components/ui/sidebar": `${HOST}/shims/sidebar`,
};

/** Visible text: [regex, replacement]. Identifiers and API values are untouched. */
const REWORD = [
  // Docs links open AgentStudio's own help (scripts/agentstudio-docs.mjs),
  // under the app's base path. Three spellings: JSX attribute, plain string
  // literal, and inside a template literal.
  [
    /href="https:\/\/docs\.dograh\.com([^"]*)"/g,
    'href={import.meta.env.BASE_URL + "studio/docs$1"}',
  ],
  [/(["'])https:\/\/docs\.dograh\.com([^"']*)\1/g, '(import.meta.env.BASE_URL + "studio/docs$2")'],
  [/https:\/\/docs\.dograh\.com/g, "${import.meta.env.BASE_URL}studio/docs"],
  [/https:\/\/(app|www)\.dograh\.com[^"'`\s)]*/g, "#"],
  [/(["'`>\s(])Dograh(?=[\s'".,:;!?)<`-])/g, "$1PayInt Voice Studio"],
];

/** Per-file class rules, for colours whose meaning depends on the surrounding markup. */
const FILE_CLASSES = {
  // The editor header was dark-only; on the themed surface its white text is plain text.
  "app/workflow/[workflowId]/components/WorkflowEditorHeader.tsx": [
    [/\b(hover:)?text-white\b/g, "$1text-text"],
  ],
};

/** Tailwind palette family -> Habibi semantic token family. Neutrals are left. */
const FAMILY = {
  orange: "brand",
  amber: "warning",
  yellow: "warning",
  red: "danger",
  rose: "danger",
  green: "success",
  emerald: "success",
  lime: "success",
  teal: "success",
  blue: "information",
  sky: "information",
  cyan: "information",
  indigo: "information",
  purple: "discovery",
  violet: "discovery",
  fuchsia: "discovery",
};
const PALETTE = new RegExp(
  `\\b(bg|text|border|ring|fill|stroke)-(${Object.keys(FAMILY).join("|")})-(\\d{2,3})(\\/\\d+)?\\b`,
  "g",
);
function toToken(_m, util, family, shade, alpha = "") {
  const sem = FAMILY[family];
  const bold = Number(shade) >= 400;
  switch (util) {
    case "bg":
      if (sem === "brand") return `bg-${bold ? "primary" : "background-brand-subtlest"}${alpha}`;
      return `bg-background-${sem}${bold ? "-bold" : ""}${alpha}`;
    case "text":
      return `text-text-${sem}${alpha}`;
    case "fill":
    case "stroke":
      return `${util}-icon-${sem}${alpha}`;
    default: // border, ring
      return `${util}-border-${sem}${alpha}`;
  }
}

/** Hardcoded palette -> Habibi tokens (className fragments only). */
const CLASSES = [
  // Decorative amber (flow-editor condition chips) is brand, not a warning.
  [/\bbg-amber-500 text-amber-950\b/g, "bg-background-brand-subtlest text-text-brand"],
  // Hardcoded dark greys (the vendor's dark-only editor chrome) -> surfaces, so
  // the editor follows the app's light/dark theme.
  [/\bhover:bg-\[#(?:2a2a2a|292929|303030)\]/g, "hover:bg-background-neutral-subtle-hovered"],
  [/\bbg-\[#1a1a1a\]/g, "bg-surface"],
  [/\bbg-\[#(?:101010|111|151515|181818)\]/g, "bg-surface-sunken"],
  [/\bbg-\[#(?:222|2a2a2a|2a2e39)\]/g, "bg-background-neutral"],
  [/\bborder-\[#(?:2a2a2a|292929|333|3a3a3a)\]/g, "border-border"],
  // Fixed greys -> theme neutrals (they were tuned for one theme only).
  [/\b(hover:)?text-(?:gray|zinc|slate|neutral)-[3-7]00\b/g, "$1text-text-subtle"],
  [/\bborder-(?:gray|slate|zinc)-[2-5]00(\/\d+)?\b/g, "border-border"],
  [/\bbg-gray-50\b/g, "bg-surface-sunken"],
  [/\bbg-gray-200\b/g, "bg-background-neutral"],
  [/\bbg-gray-500\/20\b/g, "bg-background-neutral"],
  [/\bbg-zinc-500\b/g, "bg-background-neutral-bold"],
  [PALETTE, toToken],
  // The vendor's call-to-action accent is our brand colour.
  [
    /\b(bg|text|border|ring|outline|fill|stroke|from|to|via|decoration)-cta(-foreground)?\b/g,
    "$1-primary$2",
  ],
  [/\bdrop-shadow-\[0_0_6px_rgba\(240,170,70,0\.8\)\]/g, ""],
];

const posix = (p) => p.split(path.sep).join("/");
const dropped = (rel) => DROP.some((d) => rel === d || rel.startsWith(d));
const isTest = (rel) => /\.(test|spec)\.(t|j)sx?$/.test(rel) || rel.includes("/__tests__/");

function transform(code, rel) {
  code = code.replace(
    /(\bfrom\s+|\bimport\s*\(\s*|\bimport\s+)(["'])([^"']+)\2/g,
    (m, lead, q, spec) => {
      // A relative import of a redirected module ("../lib/apiClient") is the
      // same module as its "@/..." spelling.
      const canonical = spec.startsWith(".")
        ? "@/" + path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec))
        : spec;
      let next = REDIRECT[canonical];
      // "@/host/<Slot>" is an extension point PayInt implements in
      // src/agentstudio-host/<Slot> (releases, voice preview, run provenance).
      if (!next && spec.startsWith("@/host/")) next = `${HOST}/${spec.slice("@/host/".length)}`;
      if (!next && spec.startsWith("@/")) next = "@/agentstudio/" + spec.slice(2);
      return next ? `${lead}${q}${next}${q}` : m;
    },
  );
  // Build-time vendor switches (hosted chat, analytics ids, backend URL) map to
  // VITE_AGENTSTUDIO_* variables that AgentStudio leaves unset: off.
  code = code.replace(
    /process\.env\.NEXT_PUBLIC_([A-Z0-9_]+)/g,
    "import.meta.env.VITE_AGENTSTUDIO_$1",
  );
  for (const [re, to] of REWORD) code = code.replace(re, to);
  for (const [re, to] of CLASSES) code = code.replace(re, to);
  for (const [re, to] of FILE_CLASSES[rel] ?? []) code = code.replace(re, to);
  return code;
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? walk(full) : [full];
  });
}

if (!fs.existsSync(SRC)) {
  console.error(`engine UI not found at ${SRC}`);
  process.exit(1);
}
// Empty rather than remove DEST: on Windows an open handle on the folder
// itself (an editor, a shell) makes removing it fail.
fs.mkdirSync(DEST, { recursive: true });
for (const entry of fs.readdirSync(DEST))
  fs.rmSync(path.join(DEST, entry), { recursive: true, force: true });
let copied = 0;
for (const file of walk(SRC)) {
  const rel = posix(path.relative(SRC, file));
  if (dropped(rel) || isTest(rel) || !/\.(tsx?|css|json)$/.test(rel)) continue;
  const out = path.join(DEST, rel);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const text = fs.readFileSync(file, "utf8");
  fs.writeFileSync(out, /\.(tsx?)$/.test(rel) ? transform(text, rel) : text);
  copied++;
}
fs.writeFileSync(
  path.join(DEST, "README.md"),
  "Generated by `scripts/port-agentstudio.mjs` from `agentstudio/engine/ui/src`.\n" +
    "Do not edit by hand: change the script's rules or `src/agentstudio-host/`.\n",
);
console.log(`ported ${copied} files into ${posix(path.relative(HABIBI, DEST))}`);
const docs = portDocs({ engineRoot: path.resolve(SRC, "../.."), habibiRoot: HABIBI });
console.log(`ported ${docs.pages} help pages and ${docs.images} images`);
