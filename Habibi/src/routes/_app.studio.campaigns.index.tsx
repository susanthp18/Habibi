import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/campaigns/page";

export const Route = createFileRoute("/_app/studio/campaigns/")({
  head: () => ({ meta: [{ title: "Campaigns · Voice Studio — PayInt" }] }),
  component: Page,
});
