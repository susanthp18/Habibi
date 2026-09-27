import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/model-configurations/page";

export const Route = createFileRoute("/_app/studio/model-configurations")({
  head: () => ({ meta: [{ title: "Models · Voice Studio — PayInt" }] }),
  component: Page,
});
