import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/workflow/[workflowId]/page";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/")({
  head: () => ({ meta: [{ title: "Agent editor · Voice Studio — PayInt" }] }),
  component: Page,
});
