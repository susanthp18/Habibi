import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/recordings")({
  head: () => ({ meta: [{ title: "Call recordings · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/components/voice-studio/CallRecordingsPage")),
});
