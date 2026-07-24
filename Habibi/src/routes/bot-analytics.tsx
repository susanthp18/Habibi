import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/bot-analytics")({
  head: () => ({
    meta: [
      {
        title: "Conversation & Bot Analytics — BigBound AI",
      },
      {
        name: "description",
        content:
          "Diagnostic analytics for the collections bot — intents, containment funnel, escalation reasons, RAG misses, latency percentiles.",
      },
      { property: "og:title", content: "Conversation & Bot Analytics" },
      {
        property: "og:description",
        content:
          "Understand why the bot fails and where to improve prompts and RAG coverage.",
      },
    ],
  }),
});
