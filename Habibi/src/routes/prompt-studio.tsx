import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/prompt-studio")({
  validateSearch: (search: Record<string, unknown>): {
    unansweredId?: string;
    note?: string;
  } => ({
    unansweredId: typeof search.unansweredId === "string" ? search.unansweredId : undefined,
    note: typeof search.note === "string" ? search.note : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Persona & Prompt Studio — BigBound AI" },
      {
        name: "description",
        content:
          "Tune the collections bot's system prompt, persona sliders, TTS voice and guardrails. Version, diff, preview and publish safely.",
      },
      { property: "og:title", content: "Persona & Prompt Studio" },
      {
        property: "og:description",
        content:
          "Author, version and publish the AI voice agent's prompt, persona and guardrails.",
      },
    ],
  }),
});
