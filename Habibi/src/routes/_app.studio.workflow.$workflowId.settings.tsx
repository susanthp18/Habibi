import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/workflow/[workflowId]/settings/page";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/settings")({
  head: () => ({ meta: [{ title: "Agent settings · Voice Studio — PayInt" }] }),
  component: Page,
});
