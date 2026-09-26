import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/studio/guardrails")({
  head: () => ({ meta: [{ title: "Guardrails · Voice Studio — PayInt" }] }),
  component: lazyRouteComponent(() => import("@/components/voice-studio/GuardrailsPage")),
});
