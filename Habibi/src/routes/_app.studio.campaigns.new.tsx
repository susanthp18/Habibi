import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/campaigns/new")({
  head: () => ({ meta: [{ title: "New campaign · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/campaigns/new/page")),
});
