import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/run/$runId")({
  head: () => ({ meta: [{ title: "Test call · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(
    () => import("@/agentstudio/app/workflow/[workflowId]/run/[runId]/page"),
  ),
});
