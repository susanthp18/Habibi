import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/releases")({
  head: () => ({ meta: [{ title: "Releases · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/components/voice-studio/ReleasesPage")),
});
