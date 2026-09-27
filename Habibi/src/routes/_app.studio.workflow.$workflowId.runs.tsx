import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/workflow/[workflowId]/runs/page";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/runs")({
  head: () => ({ meta: [{ title: "Agent runs · Voice Studio — PayInt" }] }),
  component: Page,
});
