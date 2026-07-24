import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/knowledge-base")({
  validateSearch: (search: Record<string, unknown>): { gapId?: string; q?: string } => ({
    gapId: typeof search.gapId === "string" ? search.gapId : undefined,
    q: typeof search.q === "string" ? search.q : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Knowledge Base (RAG) Manager — BigBound AI" },
      {
        name: "description",
        content:
          "Upload, chunk and manage the policy PDFs, SOPs and FAQ pairs the collections bot retrieves at runtime. Test retrieval, close coverage gaps and control what the bot can quote.",
      },
      { property: "og:title", content: "Knowledge Base (RAG) Manager" },
      {
        property: "og:description",
        content:
          "RAG source management with chunk inspector, test-query panel and analytics-driven gap closure.",
      },
    ],
  }),
});
