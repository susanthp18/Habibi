import { createFileRoute } from "@tanstack/react-router";
import { StudioMcpKeys } from "@/components/voice-studio/StudioMcpKeys";

export const Route = createFileRoute("/_app/studio/mcp-keys")({
  head: () => ({ meta: [{ title: "Voice Studio MCP keys — PayInt" }] }),
  component: StudioMcpKeys,
});
