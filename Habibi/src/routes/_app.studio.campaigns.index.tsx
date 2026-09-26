import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/campaigns/")({
  head: () => ({ meta: [{ title: "Campaigns · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/campaigns/page")),
});
