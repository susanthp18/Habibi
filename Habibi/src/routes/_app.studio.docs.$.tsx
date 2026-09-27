import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio-host/DocsPage";

export const Route = createFileRoute("/_app/studio/docs/$")({
  head: () => ({ meta: [{ title: "Help · Voice Studio — PayInt" }] }),
  component: Page,
});
