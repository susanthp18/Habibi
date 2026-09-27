import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/campaigns/[campaignId]/page";

export const Route = createFileRoute("/_app/studio/campaigns/$campaignId/")({
  head: () => ({ meta: [{ title: "Campaign · Voice Studio — PayInt" }] }),
  component: Page,
});
