import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/")({
  head: () => ({ meta: [{ title: "Voice agents · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio-host/WorkflowListPage")),
});
