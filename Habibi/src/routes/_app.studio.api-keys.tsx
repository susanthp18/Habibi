import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/api-keys")({
  head: () => ({ meta: [{ title: "Developers · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/api-keys/page")),
});
