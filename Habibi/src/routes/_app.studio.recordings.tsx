import { createFileRoute } from "@tanstack/react-router";

import Page from "@/components/voice-studio/CallRecordingsPage";

export const Route = createFileRoute("/_app/studio/recordings")({
  head: () => ({ meta: [{ title: "Call recordings · Voice Studio — PayInt" }] }),
  component: Page,
});
