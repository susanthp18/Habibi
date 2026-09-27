import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/recordings/page";

export const Route = createFileRoute("/_app/studio/audio-library")({
  head: () => ({ meta: [{ title: "Audio Library · Voice Studio — PayInt" }] }),
  component: Page,
});
