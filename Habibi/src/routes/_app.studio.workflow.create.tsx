import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/workflow/create")({
  head: () => ({ meta: [{ title: "New agent · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/workflow/create/page")),
});
