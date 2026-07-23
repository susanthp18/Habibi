import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, PlayCircle, History } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { RoutingStats } from "@/components/routing/RoutingStats";
import { RuleList } from "@/components/routing/RuleList";
import { InspectorPanel, type InspectorTab } from "@/components/routing/InspectorPanel";
import {
  createRoutingRule,
  deleteRoutingRule,
  reorderRoutingRules,
  saveRoutingRule,
  toggleRoutingRule,
  useRoutingAudit,
  useRoutingRules,
} from "@/api/routing";
import { newBlankRule, type Rule } from "@/data/routing-seed";

export const Route = createFileRoute("/routing")({
  head: () => ({
    meta: [
      { title: "Routing & Logic Builder — BigBound AI" },
      {
        name: "description",
        content:
          "Author and test the rules that decide when the collections bot escalates, hands off, throttles or takes automated actions.",
      },
      { property: "og:title", content: "Routing & Logic Builder" },
      {
        property: "og:description",
        content:
          "Priority-ordered rule engine with simulator and audit log for the inbound collections bot.",
      },
    ],
  }),
  component: RoutingPage,
});

const cid = () => Math.random().toString(36).slice(2, 9);

function RoutingPage() {
  const queryClient = useQueryClient();
  const { data: remoteRules } = useRoutingRules();
  const { data: audit = [] } = useRoutingAudit();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<InspectorTab>("editor");

  const rules = remoteRules ?? [];

  useEffect(() => {
    if (!selectedId && rules.length > 0) {
      setSelectedId(rules[0]!.id);
    }
  }, [selectedId, rules]);

  const selected = rules.find((r) => r.id === selectedId) ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["routing-rules"] });
    void queryClient.invalidateQueries({ queryKey: ["routing-audit"] });
  };

  const handleNew = () => {
    const r = newBlankRule("New rule");
    void createRoutingRule(r)
      .then((created) => {
        invalidate();
        setSelectedId(created.id);
        setTab("editor");
        toast.success("New rule added — configure conditions and action.");
      })
      .catch((err: Error) => toast.error("Could not create rule", { description: err.message }));
  };

  const handleSave = (r: Rule) => {
    void saveRoutingRule(r)
      .then(() => {
        invalidate();
        toast.success("Rule saved.");
      })
      .catch((err: Error) => toast.error("Could not save rule", { description: err.message }));
  };

  const handleSaveAndTest = (r: Rule) => {
    handleSave(r);
    setTab("sim");
  };

  const handleToggle = (id: string, v: boolean) => {
    void toggleRoutingRule(id, v)
      .then(() => invalidate())
      .catch((err: Error) => toast.error("Could not toggle rule", { description: err.message }));
  };

  const handleDuplicate = (id: string) => {
    const r = rules.find((x) => x.id === id);
    if (!r) return;
    const copy: Rule = {
      ...r,
      id: `r_${cid()}`,
      name: `${r.name} (copy)`,
      triggersLast24h: 0,
    };
    void createRoutingRule(copy)
      .then((created) => {
        invalidate();
        setSelectedId(created.id);
        toast.success("Rule duplicated.");
      })
      .catch((err: Error) => toast.error("Could not duplicate", { description: err.message }));
  };

  const handleDelete = (id: string) => {
    const r = rules.find((x) => x.id === id);
    if (!r) return;
    void deleteRoutingRule(id)
      .then(() => {
        invalidate();
        if (selectedId === id) setSelectedId(null);
        toast.success("Rule deleted.");
      })
      .catch((err: Error) => toast.error("Could not delete", { description: err.message }));
  };

  const handleReorder = (from: number, to: number) => {
    const next = [...rules];
    const [moved] = next.splice(from, 1);
    if (!moved) return;
    next.splice(to, 0, moved);
    void reorderRoutingRules(next.map((r) => r.id))
      .then(() => invalidate())
      .catch((err: Error) => toast.error("Could not reorder", { description: err.message }));
  };

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-[18px] font-semibold text-brand-navy">Routing & Logic Builder</h1>
              <p className="text-[12px] text-text-secondary">
                Priority-ordered rules control what the bot does next — escalate, hand off, throttle or
                comply.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setTab("sim")}>
                <PlayCircle className="h-4 w-4" />
                Simulate
              </Button>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setTab("audit")}>
                <History className="h-4 w-4" />
                Audit log
              </Button>
              <Button
                size="sm"
                className="gap-1.5 bg-brand-primary hover:bg-brand-primary-dark"
                onClick={handleNew}
              >
                <Plus className="h-4 w-4" />
                New rule
              </Button>
            </div>
          </div>
          <div className="mt-3">
            <RoutingStats rules={rules} />
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col xl:basis-2/3">
            <RuleList
              rules={rules}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setTab("editor");
              }}
              onToggle={handleToggle}
              onEdit={(id) => {
                setSelectedId(id);
                setTab("editor");
              }}
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
