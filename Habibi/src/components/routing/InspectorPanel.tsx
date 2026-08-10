import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { AuditEntry, Rule } from "@/data/routing-seed";
import { RuleEditor } from "./RuleEditor";
import { Simulator } from "./Simulator";
import { AuditLog } from "./AuditLog";

export type InspectorTab = "editor" | "sim" | "audit";

type Props = {
  tab: InspectorTab;
  onTab: (t: InspectorTab) => void;
  editingRule: Rule | null;
  rules: Rule[];
  audit: AuditEntry[];
  onSaveRule: (r: Rule) => void;
  onSaveAndTest: (r: Rule) => void;
  onCancelEdit: () => void;
  onClose?: () => void;
};

export function InspectorPanel({ tab, onTab, editingRule, rules, audit, onSaveRule, onSaveAndTest, onCancelEdit, onClose }: Props) {
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <div className="flex shrink-0 items-center border-b border-border bg-surface">
        <Tabs value={tab} onValueChange={(v) => onTab(v as InspectorTab)} className="flex-1">
          <TabsList className="h-500 w-full justify-start rounded-none bg-transparent p-0">
            <TabsTrigger value="editor" className="rounded-none border-b-2 border-transparent px-200 data-[state=active]:border-border-brand data-[state=active]:bg-transparent data-[state=active]:shadow-none">
              Rule editor
            </TabsTrigger>
            <TabsTrigger value="sim" className="rounded-none border-b-2 border-transparent px-200 data-[state=active]:border-border-brand data-[state=active]:bg-transparent data-[state=active]:shadow-none">
              Simulator
            </TabsTrigger>
            <TabsTrigger value="audit" className="rounded-none border-b-2 border-transparent px-200 data-[state=active]:border-border-brand data-[state=active]:bg-transparent data-[state=active]:shadow-none">
              Audit log
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {onClose && (
          <Button variant="ghost" size="icon" className="mr-050 h-400 w-400" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {tab === "editor" && (
        editingRule ? (
          <RuleEditor
            key={editingRule.id}
            rule={editingRule}
            onSave={onSaveRule}
            onSaveAndTest={onSaveAndTest}
            onCancel={onCancelEdit}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center p-400 text-center text-body-small text-text-subtlest">
            Select a rule to edit, or create a new one.
          </div>
        )
      )}
      {tab === "sim" && <Simulator rules={rules} />}
      {tab === "audit" && <AuditLog entries={audit} />}
    </div>
  );
}
