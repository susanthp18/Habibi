import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/campaigns/$campaignId/")({
  head: () => ({ meta: [{ title: "Campaign · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/campaigns/[campaignId]/page")),
});
