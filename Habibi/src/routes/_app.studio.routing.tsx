import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/routing")({
  head: () => ({ meta: [{ title: "Agent routing · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/components/voice-studio/RoutingPage")),
});
