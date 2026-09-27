import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/campaigns/[campaignId]/edit/page";

export const Route = createFileRoute("/_app/studio/campaigns/$campaignId/edit")({
  head: () => ({ meta: [{ title: "Edit campaign · Voice Studio — PayInt" }] }),
  component: Page,
});
