import { createFileRoute } from "@tanstack/react-router";

import Page from "@/components/voice-studio/GuardrailsPage";

export const Route = createFileRoute("/_app/studio/guardrails")({
  head: () => ({ meta: [{ title: "Guardrails · Voice Studio — PayInt" }] }),
  component: Page,
});
