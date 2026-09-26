import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/telephony-configurations/$configId")({
  head: () => ({ meta: [{ title: "Telephony configuration · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(
    () => import("@/agentstudio/app/telephony-configurations/[configId]/page"),
  ),
});
