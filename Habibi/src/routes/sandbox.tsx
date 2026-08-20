import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/sandbox")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { promptVersionId?: string; skillSlug?: string; botId?: string } => ({
    promptVersionId:
      typeof search.promptVersionId === "string" ? search.promptVersionId : undefined,
    skillSlug: typeof search.skillSlug === "string" ? search.skillSlug : undefined,
    botId: typeof search.botId === "string" ? search.botId : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Call Simulation Sandbox — BigBound AI" },
      {
        name: "description",
        content:
          "Safely test the collections bot against synthetic scenarios. Inspect retrieval, intent and sentiment, then promote to production.",
      },
      { property: "og:title", content: "Call Simulation Sandbox" },
      {
        property: "og:description",
        content:
          "Text or talk to the voice collections bot with a chosen prompt version and KB snapshot.",
      },
    ],
  }),
});
