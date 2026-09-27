import { createFileRoute } from "@tanstack/react-router";

import Page from "@/components/voice-studio/ChecksPage";

export const Route = createFileRoute("/_app/studio/checks")({
  head: () => ({ meta: [{ title: "Checks · Voice Studio — PayInt" }] }),
  component: Page,
});
