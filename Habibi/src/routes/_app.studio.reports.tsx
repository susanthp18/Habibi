import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/reports/page";

export const Route = createFileRoute("/_app/studio/reports")({
  head: () => ({ meta: [{ title: "Reports · Voice Studio — PayInt" }] }),
  component: Page,
});
