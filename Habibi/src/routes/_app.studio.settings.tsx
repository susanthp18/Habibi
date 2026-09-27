import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/settings/page";

export const Route = createFileRoute("/_app/studio/settings")({
  head: () => ({ meta: [{ title: "Settings · Voice Studio — PayInt" }] }),
  component: Page,
});
