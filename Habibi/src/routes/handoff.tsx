import { createFileRoute } from "@tanstack/react-router";

export type HandoffSearch = {
  interactionId?: string;
  customerId?: string;
  mode?: "monitor";
};

export const Route = createFileRoute("/handoff")({
  validateSearch: (search: Record<string, unknown>): HandoffSearch => ({
    interactionId: typeof search.interactionId === "string" ? search.interactionId : undefined,
    customerId: typeof search.customerId === "string" ? search.customerId : undefined,
    mode: search.mode === "monitor" ? "monitor" : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Handoff Hub — Live Escalated Call" },
      {
        name: "description",
        content:
          "Split-screen cockpit for a live escalated voice call — streaming transcript, live sentiment, AI-suggested responses, compliance checklist, and post-call wrap-up.",
      },
      { property: "og:title", content: "Handoff Hub — Live Escalated Call" },
      {
        property: "og:description",
        content:
          "Real-time human-agent cockpit for escalated collections calls with sentiment, RAG suggestions, and compliance tracking.",
      },
    ],
  }),
});
