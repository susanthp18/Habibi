import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/campaigns/$campaignId/edit")({
  head: () => ({ meta: [{ title: "Edit campaign · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/campaigns/[campaignId]/edit/page")),
});
