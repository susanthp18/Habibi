import { createFileRoute } from "@tanstack/react-router";

const TABS = [
  "today",
  "decisions",
  "results",
  "strategy",
  "cases",
  "holds",
  "mandates",
  "field",
  "legal",
  "advanced",
] as const;

/** Old links keep working: the scoreboard and model health live under Advanced. */
const RENAMED: Record<string, (typeof TABS)[number]> = { insights: "advanced", models: "advanced" };

export type TreatmentSearch = {
  tab?: (typeof TABS)[number];
  customerId?: string;
};

export const Route = createFileRoute("/_app/treatment")({
  validateSearch: (search: Record<string, unknown>): TreatmentSearch => {
    const tab = TABS.find((t) => t === search.tab) ?? RENAMED[String(search.tab)];
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
          "What the decision engine decided for each borrower, why, what happened, whether it is working, and what it has learned.",
      },
      { property: "og:title", content: "Decision Intelligence (Next-Best-Treatment)" },
      {
        property: "og:description",
        content:
          "Every decision with its reasons and evidence, the engine's health, and its measured effect.",
      },
    ],
  }),
});
