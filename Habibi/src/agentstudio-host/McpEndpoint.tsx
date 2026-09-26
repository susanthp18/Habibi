/**
 * Host slot "@/host/McpEndpoint": how an AI assistant connects to Voice Studio
 * authoring, in PayInt's deployment.
 *
 * The engine's own MCPSection advertises `<engine>/api/v1/mcp/` with an engine
 * API key. Neither works here: that path is on the Studio gateway's deny list
 * (routers/agentstudio_gateway.py), and an engine API key is not a PayInt
 * credential, so the link to mint one just bounced through Microsoft sign-in
 * and landed back on the workspace. PayInt exposes its own authoring gateway
 * at /studio-mcp/, keyed by a revocable per-user `vsm_` key, and that is what
 * this points at.
 */
import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import { STUDIO_MCP_URL } from "@/api/studio-mcp";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export default function McpEndpoint() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(STUDIO_MCP_URL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy the endpoint");
    }
  }

  return (
    <div className="flex flex-col gap-150">
      <div className="flex flex-col gap-050">
        <Label>MCP endpoint</Label>
        <p className="text-body-small text-text-subtle">
          Connect Claude Code, Claude Desktop or Cursor to author agents and tools over Streamable
          HTTP. Authenticate with a Voice Studio MCP key in the <code>Authorization: Bearer</code>{" "}
          header — not an engine API key, and not your PayInt sign-in.
        </p>
        <div className="flex items-center gap-100">
          <code className="flex-1 break-all rounded bg-surface-sunken px-100 py-050 text-body-small">
            {STUDIO_MCP_URL}
          </code>
          <Button variant="subtle" size="compact" onClick={() => void copy()}>
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-050">
        <Label>Keys</Label>
        <p className="text-body-small text-text-subtle">
          Each key belongs to one person, expires within 90 days and can be rotated or revoked. Its
          scopes decide what the assistant may do: <code>studio.read</code> to read catalogs,{" "}
          <code>studio.edit</code> to edit drafts. Publishing an agent and approving a tool revision
          are never available over MCP — a named reviewer does those here.
        </p>
        <Link to="/studio/mcp-keys" className="w-fit">
          <Button variant="subtle" size="compact">
            Manage MCP keys
            <ExternalLink className="ml-050 size-4" />
          </Button>
        </Link>
      </div>
    </div>
  );
}
