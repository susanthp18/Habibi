/**
 * Reproduces the Customer 360 Overview crash against live API payload.
 * Run: npx --yes tsx --tsconfig tsconfig.json scripts/test-c360-insights.ts
 */
import { deriveCustomerInsights } from "../src/lib/customerInsights";
import type { Customer } from "../src/data/customer360-seed";

async function main() {
  const base = process.env.VITE_API_BASE_URL || "http://localhost:8000";
  const key = process.env.VITE_API_KEY || process.env.API_KEY || "";
  const id = process.argv[2] || "cust-susanth";

  const headers: Record<string, string> = { Accept: "application/json" };
  if (key) headers["X-API-Key"] = key;

  const res = await fetch(`${base}/customers/${id}`, { headers });
  if (!res.ok) {
    console.error(`FAIL: GET /customers/${id} -> ${res.status}`);
    process.exit(1);
  }
  const customer = (await res.json()) as Customer;
  const nullSummaries = (customer.interactions || []).filter((i) => i.summary == null).length;
  const nullDisp = (customer.interactions || []).filter((i) => i.disposition == null).length;
  console.log(
    JSON.stringify({
      id: customer.id,
      name: customer.name,
      minimumDue: customer.minimumDue,
      interactions: customer.interactions?.length ?? 0,
      nullSummaries,
      nullDisp,
    }),
  );

  // Old crash path
  let oldWouldCrash = false;
  for (const ix of customer.interactions || []) {
    try {
      // @ts-expect-error intentional probe of nullable summary
      void ix.summary.slice(0, 120);
    } catch {
      oldWouldCrash = true;
      break;
    }
  }
  console.log("old_summary_slice_would_crash=", oldWouldCrash || nullSummaries > 0);

  const insights = deriveCustomerInsights(customer);
  console.log(
    "OK",
    JSON.stringify({
      summary: insights.summary.length,
      nba: insights.nba.length,
      activity: insights.activity.length,
      metrics: insights.metrics,
      firstInsight: insights.summary[0]?.text?.slice(0, 160),
    }),
  );
}

main().catch((err) => {
  console.error("FAIL", err);
  process.exit(1);
});
