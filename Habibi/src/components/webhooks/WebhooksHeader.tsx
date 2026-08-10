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
    <div className="flex shrink-0 items-center justify-between gap-200 border-b border-border bg-surface px-300 py-150">
      <div>
        <h1 className="text-[0.875rem] font-semibold text-text">
          Webhooks & Event Subscriptions
        </h1>
        <p className="text-body-small text-text-subtle">
          Register downstream endpoints, subscribe them to CRM events, and monitor deliveries.
        </p>
      </div>
      <div className="flex items-center gap-100">
        <Button variant="outline" size="sm" onClick={onCatalog}>
          <BookOpen className="mr-075 h-3.5 w-3.5" /> Event catalog
        </Button>
        <Button variant="outline" size="sm" onClick={onRotateAll}>
          <KeyRound className="mr-075 h-3.5 w-3.5" /> Rotate all
        </Button>
        <Button size="sm" onClick={onNew}>
          <Plus className="mr-075 h-3.5 w-3.5" /> New endpoint
        </Button>
      </div>
    </div>
  );
}
