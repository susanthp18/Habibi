import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/telephony-configurations/")({
  head: () => ({ meta: [{ title: "Telephony · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/agentstudio/app/telephony-configurations/page")),
});
