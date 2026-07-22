import { Plus, BookOpen, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";

export function WebhooksHeader({
  onNew,
  onCatalog,
  onRotateAll,
}: {
  onNew: () => void;
  onCatalog: () => void;
  onRotateAll: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-4 border-b border-[var(--border-token)] bg-surface-card px-6 py-3">
      <div>
        <h1 className="text-[15px] font-semibold text-brand-navy">
          Webhooks & Event Subscriptions
        </h1>
        <p className="text-[12px] text-text-secondary">
          Register downstream endpoints, subscribe them to CRM events, and monitor deliveries.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onCatalog}>
          <BookOpen className="mr-1.5 h-3.5 w-3.5" /> Event catalog
        </Button>
        <Button variant="outline" size="sm" onClick={onRotateAll}>
          <KeyRound className="mr-1.5 h-3.5 w-3.5" /> Rotate all
        </Button>
        <Button size="sm" onClick={onNew}>
          <Plus className="mr-1.5 h-3.5 w-3.5" /> New endpoint
        </Button>
      </div>
    </div>
  );
}
