import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/tools/[toolUuid]/page";

export const Route = createFileRoute("/_app/studio/tools/$toolUuid")({
  head: () => ({ meta: [{ title: "Tool · Voice Studio — PayInt" }] }),
  component: Page,
});
