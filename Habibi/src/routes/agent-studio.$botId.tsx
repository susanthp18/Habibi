import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/agent-studio/$botId")({
  validateSearch: (search: Record<string, unknown>): {
    unansweredId?: string;
    note?: string;
  } => ({
    unansweredId: typeof search.unansweredId === "string" ? search.unansweredId : undefined,
    note: typeof search.note === "string" ? search.note : undefined,
  }),
  head: ({ params }) => ({
    meta: [
      { title: `${params.botId} — Agent studio` },
      {
        name: "description",
        content: "Edit a first-party agent card. Publish is a compiler.",
      },
    ],
  }),
});
