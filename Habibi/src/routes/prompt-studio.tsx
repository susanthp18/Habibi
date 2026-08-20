import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/prompt-studio")({
  validateSearch: (search: Record<string, unknown>): {
    unansweredId?: string;
    note?: string;
  } => ({
    unansweredId: typeof search.unansweredId === "string" ? search.unansweredId : undefined,
    note: typeof search.note === "string" ? search.note : undefined,
  }),
  beforeLoad: ({ search }) => {
    if (search.unansweredId) {
      throw redirect({
        to: "/agent-studio/$botId",
        params: { botId: "kaia-v2-4" },
        search,
      });
    }
    throw redirect({ to: "/agent-studio" });
  },
  head: () => ({
    meta: [
      { title: "Agent studio — BigBound AI" },
      {
        name: "description",
        content:
          "Tune an agent card's system prompt, persona sliders, TTS voice and guardrails. Version, diff, preview and publish safely.",
      },
      { property: "og:title", content: "Agent studio" },
    ],
  }),
});
