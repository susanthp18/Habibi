import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { useConnectors } from "@/api/integrations";
import { useCompilePreview } from "@/api/agent-studio";
import { gateTone } from "@/lib/gate-status";
import { isAuthoredCard, type AgentCard } from "@/api/agent-card";
import { QueryState } from "@/components/ui/query-state";
import { NotAuthoredNotice } from "./NotAuthoredNotice";

export function ConnectorsTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const connectorsQuery = useConnectors();
  // G10 is skipped, not faked green, while MCP_CLIENT_ENABLED is off. The tab
  // says so, because "bound" otherwise reads as "checked".
  const preview = useCompilePreview(botId, { agentCard: card }, isAuthoredCard(card));
  const g10 = preview.data?.gates.find((g) => g.gate === "G10");
  const bound = new Set(
    (card.connectors ?? []).map((c) => c.connector_id).filter(Boolean) as string[],
  );
  const approved = (connectorsQuery.data ?? []).filter((c) => c.status === "approved");
  // A binding outlives approval. The list rendered `approved` only and the
  // Unbind control lives inside that map, so a card bound to a connector that
  // was later de-approved kept the binding with no way in the UI to remove it —
  // while G10 refused the publish for exactly that binding. Shown here, marked,
  // with Unbind still reachable.
  const boundNotApproved = (connectorsQuery.data ?? []).filter(
    (c) => c.status !== "approved" && (bound.has(c.id) || bound.has(c.slug)),
  );
  // And the harder case: bound to a connector the registry no longer returns at
  // all. There is no display name to show, only the id the card carries.
  const orphanedBindings = (card.connectors ?? [])
    .map((c) => String(c.connector_id ?? ""))
    .filter((id) => id && !(connectorsQuery.data ?? []).some((c) => c.id === id || c.slug === id));
  const prefixes = (card.connectors ?? []).flatMap((c) => c.allow_prefixes ?? []);
  const editable = Boolean(onChange) && isAuthoredCard(card);
  // Same alias trap as skills: the POST /connectors endpoint stamps the row id
  // while this tab wrote the slug, so Unbind matched nothing on any card bound
  // through the API. get_connector resolves either, so binding by slug is fine
  // — only the removal had to widen.
  const toggle = (aliases: string[], prefixesFor: string[]) => {
    if (!onChange) return;
    const on = aliases.some((a) => bound.has(a));
    const next = on
      ? (card.connectors ?? []).filter((c) => !aliases.includes(String(c.connector_id)))
      : [...(card.connectors ?? []), { connector_id: aliases[0], allow_prefixes: prefixesFor }];
    onChange({ ...card, connectors: next });
  };

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Bind <span className="font-semibold">approved</span> connectors only. Compiler G10 checks
        HTTPS, data-class, and health. <span className="font-mono">ext.*</span> tools stay off the
        idle mouth so G6 does not count them against the 12-tool SLO. Voice has no MCP renderer —
        bound connectors are <span className="font-semibold">unsupported</span> on a call, not
        silently uncallable.
      </p>
      {isAuthoredCard(card) && g10 ? (
        <Lozenge tone={gateTone(g10.status)} title={g10.detail || undefined}>
          {g10.gate} {g10.status}
          {g10.detail ? ` — ${g10.detail}` : ""}
        </Lozenge>
      ) : null}
      {!editable && onChange ? <NotAuthoredNotice what="connector bindings" /> : null}
      {prefixes.length > 0 ? (
        <div className="rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          Bound prefixes: {prefixes.join(", ")}. These tools can enter the compiled text grant; the
          voice grant excludes them because no voice connector renderer exists.
        </div>
      ) : null}
      <QueryState
        query={connectorsQuery}
        label="connectors"
        empty={
          approved.length === 0 ? (
            // Naming the screen without offering it left the tab a dead end: the
            // only way forward was to know where Integrations lives and go there
            // by hand. Same Link treatment the Guardrails tab gives the
            // Redaction Hub.
            //
            // Reachable ONLY on a successful, empty response now. It used to be
            // the fallback for a failed one too, so an unreachable API produced
            // a confident instruction to go and approve connectors that were
            // already approved.
            <div className="space-y-100 rounded-medium border border-border p-150 text-body-small text-text-subtle">
              <p>
                No approved connectors. A connector has to be registered and approved before a card
                can bind it — G10 rejects a binding to anything else.
              </p>
              <Link
                to="/integrations"
                className="inline-flex items-center gap-050 text-text-brand hover:underline"
              >
                Approve connectors on Integrations <ExternalLink className="h-3 w-3" />
              </Link>
            </div>
          ) : null
        }
      >
        <ul className="divide-y divide-border rounded-medium border border-border">
          {approved.map((conn) => {
            const on = bound.has(conn.id) || bound.has(conn.slug);
            return (
              <li key={conn.id} className="flex items-start justify-between gap-150 px-150 py-100">
                <div>
                  <div className="font-medium">{conn.displayName}</div>
                  <div className="font-mono text-body-tiny text-text-subtle">
                    {conn.slug} · {(conn.allowPrefixes ?? []).join(" ")}
                  </div>
                  <div className="mt-050 text-body-tiny text-text-subtle">
                    {(conn.dataClass ?? []).join(", ")} · {conn.health}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!editable}
                  onClick={() => toggle([conn.slug, conn.id], conn.allowPrefixes ?? [])}
                >
                  {on ? "Unbind" : "Bind"}
                </Button>
              </li>
            );
          })}
          {boundNotApproved.map((conn) => (
            <li
              key={conn.id}
              className="flex items-start justify-between gap-150 bg-background-warning-subtler px-150 py-100"
            >
              <div>
                <div className="font-medium">
                  {conn.displayName}{" "}
                  <Lozenge tone="warning">no longer approved · {conn.status}</Lozenge>
                </div>
                <div className="font-mono text-body-tiny text-text-subtle">{conn.slug}</div>
                <div className="mt-050 text-body-tiny text-text-warning-bolder">
                  This card is still bound to it, and G10 refuses a publish while it is.
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!editable}
                onClick={() => toggle([conn.slug, conn.id], conn.allowPrefixes ?? [])}
              >
                Unbind
              </Button>
            </li>
          ))}
          {orphanedBindings.map((id) => (
            <li
              key={id}
              className="flex items-start justify-between gap-150 bg-background-warning-subtler px-150 py-100"
            >
              <div>
                <div className="font-medium">
                  <span className="font-mono">{id}</span>{" "}
                  <Lozenge tone="warning">not in the registry</Lozenge>
                </div>
                <div className="mt-050 text-body-tiny text-text-warning-bolder">
                  Bound by this card, and the connector registry does not return it. Unbind is the
                  only thing left to do with it.
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!editable}
                onClick={() => toggle([id], [])}
              >
                Unbind
              </Button>
            </li>
          ))}
        </ul>
      </QueryState>
    </div>
  );
}
