import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Plus, PlayCircle, History } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { RoutingStats } from "@/components/routing/RoutingStats";
import { RuleList } from "@/components/routing/RuleList";
import { InspectorPanel, type InspectorTab } from "@/components/routing/InspectorPanel";
import {
  AUDIT_SEED,
  RULES_SEED,
  newBlankRule,
  type AuditEntry,
  type Rule,
} from "@/data/routing-seed";

export const Route = createFileRoute("/routing")({
  head: () => ({
    meta: [
      { title: "Routing & Logic Builder — Collections Agent" },
      { name: "description", content: "Author and test the rules that decide when the collections bot escalates, hands off, throttles or takes automated actions." },
      { property: "og:title", content: "Routing & Logic Builder" },
      { property: "og:description", content: "Priority-ordered rule engine with simulator and audit log for the inbound collections bot." },
    ],
  }),
  component: RoutingPage,
});

const cid = () => Math.random().toString(36).slice(2, 9);

function RoutingPage() {
  const [rules, setRules] = useState<Rule[]>(RULES_SEED);
  const [audit, setAudit] = useState<AuditEntry[]>(AUDIT_SEED);
  const [selectedId, setSelectedId] = useState<string | null>(RULES_SEED[0]?.id ?? null);
  const [tab, setTab] = useState<InspectorTab>("editor");

  const selected = rules.find(r => r.id === selectedId) ?? null;

  const pushAudit = (a: Omit<AuditEntry, "id" | "at" | "author">) => {
    setAudit(prev => [...prev, { ...a, id: cid(), at: new Date().toISOString(), author: "You" }]);
  };

  const handleNew = () => {
    const r = newBlankRule("New rule");
    setRules(prev => [...prev, r]);
    setSelectedId(r.id);
    setTab("editor");
    pushAudit({ ruleId: r.id, ruleName: r.name, action: "created", summary: "Rule created" });
    toast.success("New rule added — configure conditions and action.");
  };

  const handleSave = (r: Rule) => {
    setRules(prev => prev.map(x => (x.id === r.id ? r : x)));
    pushAudit({ ruleId: r.id, ruleName: r.name, action: "edited", summary: `Updated ${r.when.length} conditions · action ${r.then.key}` });
    toast.success("Rule saved.");
  };

  const handleSaveAndTest = (r: Rule) => {
    handleSave(r);
    setTab("sim");
  };

  const handleToggle = (id: string, v: boolean) => {
    const r = rules.find(x => x.id === id);
    if (!r) return;
    setRules(prev => prev.map(x => (x.id === id ? { ...x, enabled: v } : x)));
    pushAudit({ ruleId: id, ruleName: r.name, action: "toggled", summary: v ? "Enabled" : "Disabled" });
  };

  const handleDuplicate = (id: string) => {
    const r = rules.find(x => x.id === id);
    if (!r) return;
    const copy: Rule = { ...r, id: `r_${cid()}`, name: `${r.name} (copy)`, triggersLast24h: 0 };
    setRules(prev => [...prev, copy]);
    pushAudit({ ruleId: copy.id, ruleName: copy.name, action: "duplicated", summary: `Copied from ${r.name}` });
    toast.success("Rule duplicated.");
  };

  const handleDelete = (id: string) => {
    const r = rules.find(x => x.id === id);
    if (!r) return;
    setRules(prev => prev.filter(x => x.id !== id));
    if (selectedId === id) setSelectedId(null);
    pushAudit({ ruleId: id, ruleName: r.name, action: "deleted", summary: "Rule deleted" });
    toast.success("Rule deleted.");
  };

  const handleReorder = (from: number, to: number) => {
    const next = [...rules];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setRules(next);
    pushAudit({ ruleId: moved.id, ruleName: moved.name, action: "reordered", summary: `priority ${from + 1} → ${to + 1}` });
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-[18px] font-semibold text-brand-navy">Routing & Logic Builder</h1>
              <p className="text-[12px] text-text-secondary">Priority-ordered rules control what the bot does next — escalate, hand off, throttle or comply.</p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setTab("sim")}><PlayCircle className="h-4 w-4" />Simulate</Button>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setTab("audit")}><History className="h-4 w-4" />Audit log</Button>
              <Button size="sm" className="gap-1.5 bg-brand-primary hover:bg-brand-primary-dark" onClick={handleNew}><Plus className="h-4 w-4" />New rule</Button>
            </div>
          </div>
          <div className="mt-3"><RoutingStats rules={rules} /></div>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col xl:basis-2/3">
            <RuleList
              rules={rules}
              selectedId={selectedId}
              onSelect={(id) => { setSelectedId(id); setTab("editor"); }}
              onToggle={handleToggle}
              onEdit={(id) => { setSelectedId(id); setTab("editor"); }}
              onDuplicate={handleDuplicate}
              onDelete={handleDelete}
              onReorder={handleReorder}
            />
          </div>
          <div className="hidden min-h-0 border-l border-[var(--border-token)] xl:flex xl:basis-1/3 xl:flex-col">
            <InspectorPanel
              tab={tab}
              onTab={setTab}
              editingRule={selected}
              rules={rules}
              audit={audit}
              onSaveRule={handleSave}
              onSaveAndTest={handleSaveAndTest}
              onCancelEdit={() => setSelectedId(null)}
            />
          </div>
        </div>
      </div>
    </AppShell>
  );
}
