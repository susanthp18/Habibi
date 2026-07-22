import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  ACTION_LABEL,
  FIELDS,
  OPERATORS_BY_TYPE,
  type ActionKey,
  type Condition,
  type ConditionNode,
  type Rule,
  type RuleCategory,
} from "@/data/routing-seed";
import { ConditionRow } from "./ConditionRow";

const CATEGORIES: RuleCategory[] = ["Escalation", "Handoff", "Throttle", "Compliance", "Routing"];

const cid = () => Math.random().toString(36).slice(2, 9);

function blankCondition(): Condition {
  const f = FIELDS[0];
  return {
    id: cid(),
    field: f.key,
    op: OPERATORS_BY_TYPE[f.type][0],
    value: f.options?.[0] ?? "",
  };
}

type Props = {
  rule: Rule;
  onSave: (r: Rule) => void;
  onCancel: () => void;
  onSaveAndTest: (r: Rule) => void;
};

export function RuleEditor({ rule, onSave, onCancel, onSaveAndTest }: Props) {
  const [draft, setDraft] = useState<Rule>(rule);
  useEffect(() => setDraft(rule), [rule.id]);

  const updateNode = (idx: number, node: ConditionNode) => {
    const next = [...draft.when];
    next[idx] = node;
    setDraft({ ...draft, when: next });
  };
  const removeNode = (idx: number) => setDraft({ ...draft, when: draft.when.filter((_, i) => i !== idx) });
  const addAnd = () => setDraft({ ...draft, when: [...draft.when, blankCondition()] });
  const addOr = () => setDraft({ ...draft, when: [...draft.when, { id: cid(), or: [blankCondition(), blankCondition()] }] });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <div>
          <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Name</Label>
          <Input className="mt-1 h-8 text-[13px]" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
        </div>
        <div>
          <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Description</Label>
          <Textarea className="mt-1 min-h-[60px] text-[12px]" value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Category</Label>
            <Select value={draft.category} onValueChange={(v) => setDraft({ ...draft, category: v as RuleCategory })}>
              <SelectTrigger className="mt-1 h-8 text-[13px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {CATEGORIES.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end justify-between">
            <div>
              <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Enabled</Label>
              <div className="mt-2"><Switch checked={draft.enabled} onCheckedChange={v => setDraft({ ...draft, enabled: v })} /></div>
            </div>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Conditions (all must match)</Label>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-7 gap-1 text-[11px]" onClick={addAnd}><Plus className="h-3 w-3" />AND</Button>
              <Button variant="outline" size="sm" className="h-7 gap-1 text-[11px]" onClick={addOr}><Plus className="h-3 w-3" />OR-group</Button>
            </div>
          </div>
          <div className="mt-2 space-y-2 rounded-lg border border-[var(--border-token)] bg-surface-sunken/50 p-2">
            {draft.when.length === 0 && (
              <div className="p-3 text-center text-[11px] text-text-muted">No conditions — this rule will never match.</div>
            )}
            {draft.when.map((node, idx) => (
              <div key={node.id} className="rounded-md border border-[var(--border-token)] bg-white p-2">
                {idx > 0 && <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-brand-primary-dark">AND</div>}
                {"or" in node ? (
                  <div className="space-y-1.5">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-600">Match ANY of:</div>
                    {node.or.map((c, ci) => (
                      <ConditionRow
                        key={c.id}
                        cond={c}
                        onChange={(nc) => {
                          const nor = [...node.or];
                          nor[ci] = nc;
                          updateNode(idx, { ...node, or: nor });
                        }}
                        onRemove={() => {
                          const nor = node.or.filter((_, i) => i !== ci);
                          if (nor.length === 0) removeNode(idx);
                          else updateNode(idx, { ...node, or: nor });
                        }}
                      />
                    ))}
                    <Button variant="ghost" size="sm" className="h-7 text-[11px]" onClick={() => updateNode(idx, { ...node, or: [...node.or, blankCondition()] })}>
                      <Plus className="mr-1 h-3 w-3" />OR condition
                    </Button>
                  </div>
                ) : (
                  <ConditionRow
                    cond={node}
                    onChange={(nc) => updateNode(idx, nc)}
                    onRemove={() => removeNode(idx)}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <Label className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Then (action)</Label>
          <Select value={draft.then.key} onValueChange={(v) => setDraft({ ...draft, then: { ...draft.then, key: v as ActionKey } })}>
            <SelectTrigger className="mt-1 h-8 text-[13px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(ACTION_LABEL).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}
            </SelectContent>
          </Select>
          {(draft.then.key === "route_specialist" || draft.then.key === "handoff_human") && (
            <Input
              className="mt-2 h-8 text-[12px]"
              placeholder="Team name (e.g. Hardship Desk)"
              value={draft.then.params?.team ?? ""}
              onChange={(e) => setDraft({ ...draft, then: { ...draft.then, params: { ...(draft.then.params ?? {}), team: e.target.value } } })}
            />
          )}
          {draft.then.key === "send_sms" && (
            <Input
              className="mt-2 h-8 text-[12px]"
              placeholder="Template id (e.g. dnd_followup_v2)"
              value={draft.then.params?.template ?? ""}
              onChange={(e) => setDraft({ ...draft, then: { ...draft.then, params: { ...(draft.then.params ?? {}), template: e.target.value } } })}
            />
          )}
          {draft.then.key === "play_disclosure" && (
            <Input
              className="mt-2 h-8 text-[12px]"
              placeholder="Disclosure doc (e.g. waiver_policy_v3)"
              value={draft.then.params?.doc ?? ""}
              onChange={(e) => setDraft({ ...draft, then: { ...draft.then, params: { ...(draft.then.params ?? {}), doc: e.target.value } } })}
            />
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center justify-end gap-2 border-t border-[var(--border-token)] bg-surface-card px-4 py-2.5">
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        <Button variant="outline" size="sm" onClick={() => onSaveAndTest(draft)}>Save & Test</Button>
        <Button size="sm" className="bg-brand-primary hover:bg-brand-primary-dark" onClick={() => onSave(draft)}>Save</Button>
      </div>
    </div>
  );
}
