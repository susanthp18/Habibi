import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/runs")({
  head: () => ({ meta: [{ title: "Agent runs · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/workflow/[workflowId]/runs/page")),
});
