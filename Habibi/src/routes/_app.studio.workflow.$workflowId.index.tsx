import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/")({
  head: () => ({ meta: [{ title: "Agent editor · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/workflow/[workflowId]/page")),
});
