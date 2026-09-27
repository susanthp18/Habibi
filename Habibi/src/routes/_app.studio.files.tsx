import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/files/page";

export const Route = createFileRoute("/_app/studio/files")({
  head: () => ({ meta: [{ title: "Knowledge base · Voice Studio — PayInt" }] }),
  component: Page,
});
