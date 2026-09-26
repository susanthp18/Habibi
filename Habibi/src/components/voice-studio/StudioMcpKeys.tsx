import { useEffect, useState } from "react";

import {
  STUDIO_MCP_URL,
  createStudioMcpKey,
  listStudioMcpKeys,
  revokeStudioMcpKey,
  rotateStudioMcpKey,
  type CreatedStudioMcpKey,
  type StudioMcpKey,
} from "@/api/studio-mcp";
import { Button } from "@/agentstudio/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/agentstudio/components/ui/card";
import { Input } from "@/agentstudio/components/ui/input";
import { Label } from "@/agentstudio/components/ui/label";

export function StudioMcpKeys() {
  const [keys, setKeys] = useState<StudioMcpKey[]>([]);
  const [name, setName] = useState("");
  const [days, setDays] = useState(30);
  const [read, setRead] = useState(true);
  const [edit, setEdit] = useState(false);
  const [shown, setShown] = useState<CreatedStudioMcpKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => setKeys(await listStudioMcpKeys());
  useEffect(() => {
    void refresh().catch((cause) => setError(String(cause)));
  }, []);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Key operation failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Voice Studio authoring keys</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Each key belongs to your user and this tenant. It can draft agents and tools through the
            Studio MCP gateway. Approval, publishing and routing stay in the UI.
          </p>
          <div>
            <Label>Key name</Label>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="My Claude Code"
            />
          </div>
          <div>
            <Label>Expires in days (1–90)</Label>
            <Input
              type="number"
              min={1}
              max={90}
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            />
          </div>
          <div className="flex gap-4 text-sm">
            <label>
              <input
                type="checkbox"
                checked={read}
                onChange={(event) => setRead(event.target.checked)}
              />{" "}
              Read catalogs
            </label>
            <label>
              <input
                type="checkbox"
                checked={edit}
                onChange={(event) => setEdit(event.target.checked)}
              />{" "}
              Edit drafts
            </label>
          </div>
          <Button
            disabled={busy || !name.trim() || (!read && !edit)}
            onClick={() =>
              run(async () => {
                setShown(
                  await createStudioMcpKey(
                    name,
                    [read && "studio.read", edit && "studio.edit"].filter(Boolean) as string[],
                    days,
                  ),
                );
                setName("");
              })
            }
          >
            Create key
          </Button>
        </CardContent>
      </Card>
      {shown && (
        <Card>
          <CardHeader>
            <CardTitle>Copy this secret now</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm">The secret is shown once and cannot be recovered later.</p>
            <code className="block break-all rounded bg-muted p-3 text-sm">{shown.key}</code>
            <div className="flex gap-2">
              <Button onClick={() => navigator.clipboard.writeText(shown.key)}>Copy secret</Button>
              <Button variant="outline" onClick={() => setShown(null)}>
                Done
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Connect Claude Code or Codex</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            Endpoint: <code>{STUDIO_MCP_URL}</code>. Store the one-time secret in a private
            environment variable named <code>VOICE_STUDIO_MCP_KEY</code>.
          </p>
          <p>
            Codex: add this to your private <code>~/.codex/config.toml</code>, then restart and run{" "}
            <code>codex mcp list</code>.
          </p>
          <pre className="overflow-auto rounded bg-muted p-3">{`[mcp_servers.voiceStudio]\nurl = "${STUDIO_MCP_URL}"\nbearer_token_env_var = "VOICE_STUDIO_MCP_KEY"`}</pre>
          <p>
            Claude Code: add this to a private <code>.mcp.json</code>, then run{" "}
            <code>claude mcp list</code> or <code>/mcp</code>.
          </p>
          <pre className="overflow-auto rounded bg-muted p-3">
            {JSON.stringify(
              {
                mcpServers: {
                  voiceStudio: {
                    type: "http",
                    url: STUDIO_MCP_URL,
                    headers: { Authorization: "Bearer ${VOICE_STUDIO_MCP_KEY}" },
                  },
                },
              },
              null,
              2,
            )}
          </pre>
          <p>
            Both connections can read catalogs and edit drafts. A separate reviewer approves live
            tool revisions, and an agent publisher releases them.
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Your keys</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {keys.map((key) => (
            <div
              key={key.id}
              className="flex flex-wrap items-center justify-between gap-3 border-t py-3 text-sm"
            >
              <div>
                <strong>{key.name}</strong> · {key.prefix}… · {key.scopes.join(", ")}
                <div className="text-muted-foreground">
                  Expires {new Date(key.expiresAt).toLocaleString()} · Last used{" "}
                  {key.lastUsedAt ? new Date(key.lastUsedAt).toLocaleString() : "never"} ·{" "}
                  {key.revoked ? "revoked" : "active"}
                </div>
              </div>
              {!key.revoked && (
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => run(async () => setShown(await rotateStudioMcpKey(key.id)))}
                  >
                    Rotate
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => run(() => revokeStudioMcpKey(key.id).then(() => undefined))}
                  >
                    Revoke
                  </Button>
                </div>
              )}
            </div>
          ))}
          {keys.length === 0 && (
            <p className="text-sm text-muted-foreground">No Studio authoring keys yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
