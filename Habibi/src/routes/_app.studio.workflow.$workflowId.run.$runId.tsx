import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/workflow/[workflowId]/run/[runId]/page";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/run/$runId")({
  head: () => ({ meta: [{ title: "Test call · Voice Studio — PayInt" }] }),
  component: Page,
});
