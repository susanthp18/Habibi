import { useEffect, useState } from "react";
import { toast } from "sonner";

import { type Guardrails, useAgentGuardrails, useSaveGuardrails } from "@/api/voice-studio";
import { can, useMe } from "@/api/me";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QueryState } from "@/components/ui/query-state";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import { AgentPicker } from "./AgentPicker";

const TOGGLES: { key: keyof Guardrails; label: string; detail: string }[] = [
  {
    key: "neverQuoteRate",
    label: "Never quote a rate",
    detail: "Flag any interest rate, APR or percentage the agent says.",
  },
  {
    key: "neverPromiseWaiver",
    label: "Never promise a waiver",
    detail: "Flag a waiver offered in reply to a waiver request.",
  },
  {
    key: "escalateLegal",
    label: "Escalate legal threats",
    detail: "A customer's legal threat raises an escalation flag.",
  },
  {
    key: "escalateAbuse",
    label: "Escalate abuse",
    detail: "Abusive language from the customer raises an escalation flag.",
  },
  {
    key: "alwaysDiscloseRecording",
    label: "Disclose recording on calls",
    detail: "Flag a call whose opening never mentions recording.",
  },
  {
    key: "refusePoliticsReligion",
    label: "Refuse politics and religion",
    detail: "Flag the agent engaging with either topic.",
  },
];

/**
 * PayInt's guardrails for a Voice Studio agent. The engine runs the
 * conversation; these rules are checked on every agent turn of its calls and
 * WhatsApp threads, and raise flags, live alerts and compliance hits.
 */
export default function GuardrailsPage() {
  const [agentId, setAgentId] = useState<number | null>(null);
  const query = useAgentGuardrails(agentId);
  const save = useSaveGuardrails(agentId);
  const { data: me } = useMe();
  const editable = can(me, "perm-agent-edit");
  const [draft, setDraft] = useState<Guardrails | null>(null);
  const [phrases, setPhrases] = useState("");

  useEffect(() => {
    if (query.data) {
      setDraft(query.data.guardrails);
      setPhrases(query.data.guardrails.prohibited.join("\n"));
    }
  }, [query.data]);

  const submit = () => {
    if (!draft) return;
    const prohibited = phrases
      .split(/[\n,]/)
      .map((p) => p.trim())
      .filter(Boolean);
    save.mutate(
      { ...draft, prohibited },
      {
        onSuccess: () => toast.success("Guardrails saved"),
        onError: (e) =>
          toast.error(`Could not save: ${e instanceof Error ? e.message : String(e)}`),
      },
    );
  };

  return (
    <div className="mx-auto max-w-[56rem] space-y-300 p-300">
      <header className="space-y-050">
        <h1 className="heading-medium font-semibold">Guardrails</h1>
        <p className="text-body-small text-text-subtle">
          Rules checked on every turn of an agent&apos;s calls and WhatsApp conversations. A broken
          rule is flagged on the conversation and raises a compliance alert.
        </p>
      </header>
      <AgentPicker value={agentId} onChange={setAgentId} />
      {agentId !== null && (
        <QueryState query={query} label="guardrails">
          {draft && (
            <section className="space-y-300">
              <div className="space-y-100">
                <Label htmlFor="vs-prohibited">Prohibited phrases</Label>
                <p className="text-body-small text-text-subtle">
                  One per line. Matched as whole words in what the agent says.
                </p>
                <Textarea
                  id="vs-prohibited"
                  rows={6}
                  value={phrases}
                  disabled={!editable}
                  onChange={(e) => setPhrases(e.target.value)}
                />
              </div>
              <ul className="divide-y divide-border rounded-medium border border-border">
                {TOGGLES.map((t) => (
                  <li key={t.key} className="flex items-center justify-between gap-200 p-150">
                    <div>
                      <p className="text-body font-semibold text-text">{t.label}</p>
                      <p className="text-body-small text-text-subtle">{t.detail}</p>
                    </div>
                    <Switch
                      aria-label={t.label}
                      checked={Boolean(draft[t.key])}
                      disabled={!editable}
                      onCheckedChange={(v) => setDraft({ ...draft, [t.key]: v })}
                    />
                  </li>
                ))}
              </ul>
              <div className="flex items-end gap-200">
                <div className="space-y-100">
                  <Label htmlFor="vs-max-turns">Turn limit</Label>
                  <Input
                    id="vs-max-turns"
                    type="number"
                    min={1}
                    max={200}
                    className="w-[8rem]"
                    value={draft.maxTurns}
                    disabled={!editable}
                    onChange={(e) => setDraft({ ...draft, maxTurns: Number(e.target.value) || 1 })}
                  />
                </div>
                <p className="pb-100 text-body-small text-text-subtle">
                  A WhatsApp conversation longer than this is handed to a person.
                </p>
              </div>
              <div className="flex justify-end gap-100">
                <Button
                  variant="secondary"
                  disabled={!editable}
                  onClick={() => {
                    if (!query.data) return;
                    setDraft(query.data.defaults);
                    setPhrases(query.data.defaults.prohibited.join("\n"));
                  }}
                >
                  Reset to defaults
                </Button>
                <Button
                  variant="primary"
                  disabled={!editable}
                  loading={save.isPending}
                  onClick={submit}
                >
                  Save
                </Button>
              </div>
            </section>
          )}
        </QueryState>
      )}
    </div>
  );
}
