import { createFileRoute } from "@tanstack/react-router";

import Page from "@/components/voice-studio/RoutingPage";

export const Route = createFileRoute("/_app/studio/routing")({
  head: () => ({ meta: [{ title: "Agent routing · Voice Studio — PayInt" }] }),
  component: Page,
});
