import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/reports")({
  head: () => ({ meta: [{ title: "Reports · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/reports/page")),
});
