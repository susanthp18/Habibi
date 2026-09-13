import { useMemo } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { CardPostCall, PostCallQa, PostCallRule } from "@/api/agent-card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { SelectField } from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CodeGrid,
  patchOutbound,
  resolvedOutbound,
  toggleIn,
  type OutboundEditorProps,
} from "./shared";

export function PostCallEditor({
  card,
  onChange,
  vocab,
  editable,
}: Omit<OutboundEditorProps, "graphEntries">) {
  const ob = resolvedOutbound(card);
  const pc = ob.post_call;
  const cardTools = useMemo(() => card.tools?.include ?? [], [card.tools]);
  // G-OB6 checks the union: a rule may name a Closer verb *or* any tool this
  // card includes, which is what lets a client add an action without a code
  // change. Offering only the verbs would hide half the vocabulary.
  const actions = useMemo(
    () => Array.from(new Set([...vocab.postCallActions, ...cardTools])).sort(),
    [vocab.postCallActions, cardTools],
  );
  const setPostCall = (next: Partial<CardPostCall>) =>
    patchOutbound(card, onChange, { post_call: { ...pc, ...next } });

  const setRule = (index: number, next: Partial<PostCallRule>) =>
    setPostCall({ on_outcome: pc.on_outcome.map((r, i) => (i === index ? { ...r, ...next } : r)) });

  const used = new Set(pc.on_outcome.map((r) => r.when));
  const unruled = vocab.outcomeCodes.filter((c) => !used.has(c));

  return (
    <div className="space-y-150 rounded-medium border border-border bg-surface p-150">
      <div>
        <h3 className="text-body font-semibold">After the call, on this card</h3>
        <p className="mt-025 max-w-prose text-body-small text-text-subtle">
          Versioned with the agent, so the sentence it said and the follow-up that sentence produced
          carry one version number.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-200">
        <label className="flex items-center gap-100 text-body-small">
          <Switch
            aria-label="Send a written record of what was agreed"
            checked={pc.written_followup}
            disabled={!editable}
            onCheckedChange={(v) => setPostCall({ written_followup: v })}
          />
          Send a written record of what was agreed
        </label>
        <label className="flex items-center gap-100 text-body-small">
          <Switch
            aria-label="Honour promises the agent made"
            checked={pc.obligations}
            disabled={!editable}
            onCheckedChange={(v) => setPostCall({ obligations: v })}
          />
          Honour promises the agent made
        </label>
        <div className="flex items-center gap-100">
          <Label htmlFor="pc-qa">QA</Label>
          <SelectField
            id="pc-qa"
            size="compact"
            className="w-[11.25rem]"
            disabled={!editable}
            value={pc.qa}
            onChange={(v) => setPostCall({ qa: v as PostCallQa })}
            options={vocab.qaModes.map((m) => ({ value: m, label: m }))}
          />
        </div>
      </div>

      <div className="space-y-100">
        <div className="flex flex-wrap items-center gap-100">
          <span className="text-body-small font-medium">Rules</span>
          <span className="text-body-tiny text-text-subtlest">
            one outcome, and what it triggers
          </span>
          <span className="ml-auto">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-400"
                  disabled={!editable || unruled.length === 0}
                >
                  <Plus aria-hidden className="size-100" />
                  {unruled.length ? "Add a rule" : "Every outcome has a rule"}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {unruled.map((c) => (
                  <DropdownMenuItem
                    key={c}
                    onSelect={() =>
                      setPostCall({ on_outcome: [...pc.on_outcome, { when: c, do: [] }] })
                    }
                  >
                    {c}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </span>
        </div>

        {pc.on_outcome.length === 0 ? (
          <p className="max-w-prose text-body-small text-text-subtle">
            No rules. Every outcome still gets recorded; nothing is triggered by it here.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-medium border border-border">
            {pc.on_outcome.map((rule, index) => (
              <li key={`${rule.when}-${index}`} className="space-y-075 px-150 py-100">
                <div className="flex items-center gap-100">
                  <span className="font-mono text-body-small font-semibold">{rule.when}</span>
                  {!vocab.outcomeCodes.includes(rule.when ?? "") ? (
                    <Lozenge tone="danger">unknown outcome — G-OB6</Lozenge>
                  ) : null}
                  <span className="ml-auto">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!editable}
                      onClick={() =>
                        setPostCall({ on_outcome: pc.on_outcome.filter((_, i) => i !== index) })
                      }
                    >
                      <Trash2 aria-hidden className="size-100" />
                      <span className="sr-only">Remove rule for {rule.when}</span>
                    </Button>
                  </span>
                </div>
                <CodeGrid
                  legend="Then"
                  options={actions}
                  selected={rule.do ?? []}
                  disabled={!editable}
                  onToggle={(a) => setRule(index, { do: toggleIn(rule.do ?? [], a) })}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
