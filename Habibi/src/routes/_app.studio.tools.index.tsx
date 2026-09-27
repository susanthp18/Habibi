import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/tools/page";

export const Route = createFileRoute("/_app/studio/tools/")({
  head: () => ({ meta: [{ title: "Tools · Voice Studio — PayInt" }] }),
  component: Page,
});
