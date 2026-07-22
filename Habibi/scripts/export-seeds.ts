// One-shot exporter: snapshots the frontend seed data to JSON so the backend
// can load the exact same dummy customers/dashboard into SQLite.
// Run:  npx tsx scripts/export-seeds.ts   (from the Habibi/ dir)
import { mkdirSync, writeFileSync } from "node:fs";

import { customers } from "../src/data/customer360-seed";
import {
  atRiskAccounts,
  botVsHuman,
  callVolumeStacked,
  heroKpis,
  kpis,
  leaderboard,
  recoveryTrend,
  sentimentDistribution,
} from "../src/data/dashboard-seed";
import { calls } from "../src/data/audit-seed";
import { leads } from "../src/data/upsell-seed";
import {
  activeCall,
  complianceItems,
  customerContext,
  dispositions,
  suggestions,
  transcriptScript,
} from "../src/data/handoff-seed";

const outDir = new URL("../../backend/seed/", import.meta.url);
mkdirSync(outDir, { recursive: true });

writeFileSync(new URL("customers.json", outDir), JSON.stringify(customers, null, 2));
writeFileSync(new URL("calls.json", outDir), JSON.stringify(calls, null, 2));
writeFileSync(new URL("leads.json", outDir), JSON.stringify(leads, null, 2));
writeFileSync(
  new URL("handoff.json", outDir),
  JSON.stringify(
    { activeCall, customerContext, transcriptScript, suggestions, complianceItems, dispositions },
    null,
    2,
  ),
);

// Base (unscaled) dashboard payload — the API applies range/segment/team scaling.
writeFileSync(
  new URL("dashboard.json", outDir),
  JSON.stringify(
    {
      heroKpis,
      kpis,
      recoveryTrend,
      callVolumeStacked,
      sentimentDistribution,
      botVsHuman,
      leaderboard,
      atRiskAccounts,
    },
    null,
    2,
  ),
);

console.log(
  `Exported ${customers.length} customers, ${calls.length} calls, ${leads.length} leads, ` +
    `dashboard + handoff snapshots to backend/seed/`,
);
