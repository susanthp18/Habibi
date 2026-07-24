import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/audit")({
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
