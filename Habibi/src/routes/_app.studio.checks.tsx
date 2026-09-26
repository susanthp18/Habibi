import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/checks")({
  head: () => ({ meta: [{ title: "Checks · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/components/voice-studio/ChecksPage")),
});
