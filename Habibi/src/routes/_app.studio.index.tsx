import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio-host/WorkflowListPage";

export const Route = createFileRoute("/_app/studio/")({
  head: () => ({ meta: [{ title: "Voice agents · Voice Studio — PayInt" }] }),
  component: Page,
});
