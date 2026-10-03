import { createFileRoute } from "@tanstack/react-router";

export type HandoffSearch = {
  interactionId?: string;
  customerId?: string;
  mode?: "monitor";
};

export const Route = createFileRoute("/_app/handoff")({
  validateSearch: (search: Record<string, unknown>): HandoffSearch => ({
    interactionId: typeof search.interactionId === "string" ? search.interactionId : undefined,
    customerId: typeof search.customerId === "string" ? search.customerId : undefined,
    mode: search.mode === "monitor" ? "monitor" : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Handoff Hub — Escalated cases" },
      {
        name: "description",
        content:
          "The follow-up desk for calls a Voice Studio agent handed to a person: the conversation before the handoff, customer context, compliance and a wrap-up that files what happened.",
      },
    ],
  }),
});
