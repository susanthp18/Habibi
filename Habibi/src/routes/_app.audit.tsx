import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/audit")({
  validateSearch: (search: Record<string, unknown>): { id?: string; t?: number } => ({
    id: typeof search.id === "string" ? search.id : undefined,
    // Seconds into the call to open the player at (Compliance "Jump to audio").
    t:
      typeof search.t === "number"
        ? search.t
        : typeof search.t === "string"
          ? Number(search.t) || undefined
          : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Audit Trail — PayInt" },
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
