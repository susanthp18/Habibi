import { createFileRoute } from "@tanstack/react-router";

import { StudioLayout } from "@/agentstudio-host/StudioLayout";

// AgentStudio (the voice-agent engine's screens) renders in the browser only:
// the screens talk to the engine through the gateway with the user's session.
export const Route = createFileRoute("/_app/studio")({
  ssr: false,
  component: StudioLayout,
});
