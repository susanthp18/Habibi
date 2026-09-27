import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/api-keys/page";

export const Route = createFileRoute("/_app/studio/api-keys")({
  head: () => ({ meta: [{ title: "Developers · Voice Studio — PayInt" }] }),
  component: Page,
});
