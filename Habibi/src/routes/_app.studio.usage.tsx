import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/usage/page";

export const Route = createFileRoute("/_app/studio/usage")({
  head: () => ({ meta: [{ title: "Agent runs · Voice Studio — PayInt" }] }),
  component: Page,
});
