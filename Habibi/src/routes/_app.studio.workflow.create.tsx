import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/workflow/create/page";

export const Route = createFileRoute("/_app/studio/workflow/create")({
  head: () => ({ meta: [{ title: "New agent · Voice Studio — PayInt" }] }),
  component: Page,
});
