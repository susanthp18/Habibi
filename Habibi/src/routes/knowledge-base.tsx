import { createFileRoute } from "@tanstack/react-router";
import type { KbTab } from "@/components/kb/KbStatsStrip";

const TABS = new Set<KbTab>(["documents", "faqs", "gaps", "test"]);

export type KnowledgeBaseSearch = {
  gapId?: string;
  q?: string;
  tab?: KbTab;
};

export const Route = createFileRoute("/knowledge-base")({
  validateSearch: (search: Record<string, unknown>): KnowledgeBaseSearch => ({
    gapId: typeof search.gapId === "string" ? search.gapId : undefined,
    q: typeof search.q === "string" ? search.q : undefined,
    tab: TABS.has(search.tab as KbTab) ? (search.tab as KbTab) : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Knowledge Base — BigBound AI" },
      {
        name: "description",
        content:
          "Upload, chunk and manage the policy PDFs, SOPs and FAQ pairs the collections bot retrieves at runtime. Test retrieval, close coverage gaps and control what the bot can quote.",
      },
      { property: "og:title", content: "Knowledge Base" },
      {
        property: "og:description",
        content:
          "RAG source management with chunk inspector, test-query panel and analytics-driven gap closure.",
      },
    ],
  }),
});
