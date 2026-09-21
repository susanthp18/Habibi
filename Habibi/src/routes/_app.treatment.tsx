import { createFileRoute } from "@tanstack/react-router";

const TABS = ["insights", "models", "cases", "holds", "mandates", "field", "legal"] as const;

export type TreatmentSearch = {
  tab?: (typeof TABS)[number];
  customerId?: string;
};

export const Route = createFileRoute("/_app/treatment")({
  validateSearch: (search: Record<string, unknown>): TreatmentSearch => {
    const tab = TABS.find((t) => t === search.tab);
    const customerId =
      typeof search.customerId === "string" && search.customerId.length > 0
        ? search.customerId
        : undefined;
    return { tab, customerId };
  },
  head: () => ({
    meta: [
      { title: "Decision Intelligence — PayInt" },
      {
        name: "description",
        content:
          "The treatment engine's shadow-mode scoreboard: coverage and suppression mix, model health, the champion/challenger ledger, open cases and collections holds.",
      },
      { property: "og:title", content: "Decision Intelligence (Next-Best-Treatment)" },
      {
        property: "og:description",
        content:
          "Read what the engine decided before it is allowed to act — coverage, suppression breakdown, drift and calibration, and the holds that veto outreach.",
      },
    ],
  }),
});
