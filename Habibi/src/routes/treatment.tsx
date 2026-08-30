import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/treatment")({
  head: () => ({
    meta: [
      { title: "Decision Intelligence — BigBound AI" },
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
