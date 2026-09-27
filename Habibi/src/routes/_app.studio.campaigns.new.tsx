import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/campaigns/new/page";

export const Route = createFileRoute("/_app/studio/campaigns/new")({
  head: () => ({ meta: [{ title: "New campaign · Voice Studio — PayInt" }] }),
  component: Page,
});
