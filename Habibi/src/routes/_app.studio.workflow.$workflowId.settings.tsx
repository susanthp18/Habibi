import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/workflow/$workflowId/settings")({
  head: () => ({ meta: [{ title: "Agent settings · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(
    () => import("@/agentstudio/app/workflow/[workflowId]/settings/page"),
  ),
});
