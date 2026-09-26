import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/tools/$toolUuid")({
  head: () => ({ meta: [{ title: "Tool · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/tools/[toolUuid]/page")),
});
