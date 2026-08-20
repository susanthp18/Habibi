import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/audit")({
  validateSearch: (search: Record<string, unknown>): { id?: string } => ({
    id: typeof search.id === "string" ? search.id : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Audit Trail — BigBound AI" },
      {
        name: "description",
        content:
          "Searchable, immutable log of every historical customer interaction with synced audio, transcript, sentiment timeline, and disclosure checklist.",
      },
      { property: "og:title", content: "Audit Trail (Call History)" },
      {
        property: "og:description",
        content:
          "Filter, review, and export any past call — audio synced to transcript, sentiment charted, compliance disclosures verified.",
      },
    ],
  }),
});
