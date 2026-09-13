import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Trash2, Plus } from "lucide-react";
import type { Endpoint, SigningAlgo, TargetSystem } from "@/api/types/webhooks";
import { useEventCatalog } from "@/api/webhooks";
import { EventPicker } from "./EventPicker";
import { QueryState } from "@/components/ui/query-state";

type Draft = Omit<Endpoint, "id" | "createdAt" | "status" | "secret" | "secretRef"> & {
  id?: string;
};

const empty = (): Draft => ({
  name: "",
  url: "https://",
  target: "Custom",
  events: [],
  algo: "HMAC-SHA256",
  retry: { attempts: 5, backoff: "exponential", maxAgeHours: 24 },
  headers: [],
});

export function EndpointSheet({
  open,
  onOpenChange,
  initial,
  onSave,
  onSaveAndTest,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  initial: Endpoint | null;
  onSave: (d: Draft) => void;
  onSaveAndTest: (d: Draft) => void;
}) {
  const catalogQuery = useEventCatalog();
  const [draft, setDraft] = useState<Draft>(empty());

  useEffect(() => {
    if (open) {
      setDraft(initial ? { ...initial } : empty());
    }
  }, [open, initial]);

  const isValid = draft.name.trim() && draft.url.startsWith("https://") && draft.events.length > 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full max-w-[37.5rem] flex-col overflow-hidden p-0 sm:max-w-[37.5rem]"
      >
        <SheetHeader className="shrink-0 border-b border-border px-300 py-200">
          <SheetTitle className="text-body font-semibold text-text">
            {initial ? "Edit endpoint" : "New endpoint"}
          </SheetTitle>
        </SheetHeader>

        <div className="flex-1 space-y-250 overflow-y-auto px-300 py-200">
          <div className="space-y-075">
            <Label className="text-body-small">Name</Label>
            <Input
              value={draft.name}
              placeholder="e.g. Finacle CBS · writeback"
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </div>

          <div className="space-y-075">
            <Label className="text-body-small">URL</Label>
            <Input
              value={draft.url}
              placeholder="https://…"
              size="compact"
              className="font-mono"
              onChange={(e) => setDraft({ ...draft, url: e.target.value })}
            />
            {!draft.url.startsWith("https://") && (
              <p className="text-body-small text-text-danger">
                Must be https:// (http blocked in production).
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-150">
            <div className="space-y-075">
              <Label className="text-body-small">Target system</Label>
              <Select
                value={draft.target}
                onValueChange={(v) => setDraft({ ...draft, target: v as TargetSystem })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(["Core Banking", "CRM", "Data Lake", "Custom"] as TargetSystem[]).map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-075">
              <Label className="text-body-small">Signing algorithm</Label>
              <Select
                value={draft.algo}
                onValueChange={(v) =>
                  setDraft({
                    ...draft,
                    algo: v as SigningAlgo,
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="HMAC-SHA256">HMAC-SHA256</SelectItem>
                  <SelectItem value="Ed25519">Ed25519</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <Separator />

          <div>
            <div className="mb-100 flex items-center justify-between">
              <Label className="text-body-small font-semibold">Event subscriptions</Label>
              <span className="text-body-small text-text-subtlest">
                {draft.events.length} selected
              </span>
            </div>
            <QueryState query={catalogQuery} label="the event catalogue">
              <EventPicker
                catalog={catalogQuery.data ?? []}
                selected={draft.events}
                columns={2}
                onChange={(events) => setDraft((d) => ({ ...d, events }))}
              />
            </QueryState>
          </div>

          <Separator />

          <div>
            <Label className="mb-100 block text-body-small font-semibold">Retry policy</Label>
            <div className="grid grid-cols-3 gap-150">
              <div className="space-y-075">
                <Label className="text-body-small">Attempts</Label>
                <Input
                  type="number"
                  min={2}
                  max={8}
                  value={draft.retry.attempts}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      retry: {
                        ...draft.retry,
                        attempts: Math.max(2, Math.min(8, +e.target.value)),
                      },
                    })
                  }
                />
              </div>
              <div className="space-y-075">
                <Label className="text-body-small">Backoff</Label>
                <Select
                  value={draft.retry.backoff}
                  onValueChange={(v) =>
                    setDraft({
                      ...draft,
                      retry: { ...draft.retry, backoff: v as "linear" | "exponential" },
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="linear">Linear</SelectItem>
                    <SelectItem value="exponential">Exponential</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-075">
                <Label className="text-body-small">Max age (h)</Label>
                <Input
                  type="number"
                  min={1}
                  max={72}
                  value={draft.retry.maxAgeHours}
                  onChange={(e) =>
                    setDraft({ ...draft, retry: { ...draft.retry, maxAgeHours: +e.target.value } })
                  }
                />
              </div>
            </div>
          </div>

          <div>
            <div className="mb-100 flex items-center justify-between">
              <Label className="text-body-small font-semibold">Custom headers</Label>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setDraft({ ...draft, headers: [...draft.headers, { key: "", value: "" }] })
                }
              >
                <Plus className="mr-050 h-3 w-3" /> Add
              </Button>
            </div>
            <div className="space-y-075">
              {draft.headers.length === 0 && (
                <p className="text-body-small text-text-subtlest">No custom headers.</p>
              )}
              {draft.headers.map((h, i) => (
                <div key={i} className="flex items-center gap-100">
                  <Input
                    placeholder="Header"
                    size="compact"
                    className="font-mono"
                    value={h.key}
                    onChange={(e) => {
                      const next = [...draft.headers];
                      next[i] = { ...h, key: e.target.value };
                      setDraft({ ...draft, headers: next });
                    }}
                  />
                  <Input
                    placeholder="Value"
                    size="compact"
                    className="font-mono"
                    value={h.value}
                    onChange={(e) => {
                      const next = [...draft.headers];
                      next[i] = { ...h, value: e.target.value };
                      setDraft({ ...draft, headers: next });
                    }}
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-400 w-400"
                    onClick={() =>
                      setDraft({ ...draft, headers: draft.headers.filter((_, j) => j !== i) })
                    }
                    aria-label="Remove header"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="shrink-0 border-t border-border px-300 py-150 flex justify-end gap-100">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="outline" disabled={!isValid} onClick={() => onSaveAndTest(draft)}>
            Save & test
          </Button>
          <Button disabled={!isValid} onClick={() => onSave(draft)}>
            {initial ? "Save changes" : "Create endpoint"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
