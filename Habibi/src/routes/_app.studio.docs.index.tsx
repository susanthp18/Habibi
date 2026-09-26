import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/docs/")({
  head: () => ({ meta: [{ title: "Help · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio-host/DocsPage")),
});
