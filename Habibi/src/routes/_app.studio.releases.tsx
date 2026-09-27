import { createFileRoute } from "@tanstack/react-router";

import Page from "@/components/voice-studio/ReleasesPage";

export const Route = createFileRoute("/_app/studio/releases")({
  head: () => ({ meta: [{ title: "Releases · Voice Studio — PayInt" }] }),
  component: Page,
});
