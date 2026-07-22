import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Trash2, Plus } from "lucide-react";
import {
  EVENT_CATALOG,
  EVENT_CATEGORIES,
  rotateSecret,
  type Endpoint,
  type EventCategory,
  type EventKey,
  type SigningAlgo,
  type TargetSystem,
} from "@/data/webhooks-seed";

type Draft = Omit<Endpoint, "id" | "createdAt" | "status"> & {
  id?: string;
};

const empty = (): Draft => ({
  name: "",
  url: "https://",
  target: "Custom",
  events: [],
  algo: "HMAC-SHA256",
  secret: rotateSecret("HMAC-SHA256"),
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
  const [draft, setDraft] = useState<Draft>(empty());

  useEffect(() => {
    if (open) {
      setDraft(initial ? { ...initial } : empty());
    }
  }, [open, initial]);

  const toggleEvent = (k: EventKey) =>
    setDraft((d) => ({
      ...d,
      events: d.events.includes(k) ? d.events.filter((x) => x !== k) : [...d.events, k],
    }));

  const toggleCategory = (cat: EventCategory) => {
    const inCat = EVENT_CATALOG.filter((e) => e.category === cat).map((e) => e.key);
    const allIn = inCat.every((k) => draft.events.includes(k));
    setDraft((d) => ({
      ...d,
      events: allIn
        ? d.events.filter((k) => !inCat.includes(k))
        : Array.from(new Set([...d.events, ...inCat])),
    }));
  };

  const isValid = draft.name.trim() && draft.url.startsWith("https://") && draft.events.length > 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full max-w-[560px] flex-col overflow-hidden p-0 sm:max-w-[560px]">
        <SheetHeader className="shrink-0 border-b border-[var(--border-token)] px-6 py-4">
          <SheetTitle className="text-[15px] font-semibold text-brand-navy">
            {initial ? "Edit endpoint" : "New endpoint"}
          </SheetTitle>
        </SheetHeader>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-4">
          <div className="space-y-1.5">
            <Label className="text-[12px]">Name</Label>
            <Input
              value={draft.name}
              placeholder="e.g. Finacle CBS · writeback"
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-[12px]">URL</Label>
            <Input
              value={draft.url}
              placeholder="https://…"
              className="font-mono text-[12px]"
              onChange={(e) => setDraft({ ...draft, url: e.target.value })}
            />
            {!draft.url.startsWith("https://") && (
              <p className="text-[11px] text-rose-600">Must be https:// (http blocked in production).</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-[12px]">Target system</Label>
              <Select
                value={draft.target}
                onValueChange={(v) => setDraft({ ...draft, target: v as TargetSystem })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(["Core Banking", "CRM", "Data Lake", "Custom"] as TargetSystem[]).map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-[12px]">Signing algorithm</Label>
              <Select
                value={draft.algo}
                onValueChange={(v) => setDraft({ ...draft, algo: v as SigningAlgo, secret: rotateSecret(v as SigningAlgo) })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="HMAC-SHA256">HMAC-SHA256</SelectItem>
                  <SelectItem value="Ed25519">Ed25519</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <Separator />

          <div>
            <div className="mb-2 flex items-center justify-between">
              <Label className="text-[12px] font-semibold">Event subscriptions</Label>
              <span className="text-[11px] text-text-muted">{draft.events.length} selected</span>
            </div>
            <div className="space-y-3">
              {EVENT_CATEGORIES.map((cat) => {
                const items = EVENT_CATALOG.filter((e) => e.category === cat);
                const allIn = items.every((e) => draft.events.includes(e.key));
                return (
                  <div key={cat} className="rounded-md border border-[var(--border-token)] p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <div className="text-[12px] font-semibold text-brand-navy">{cat}</div>
                      <button
                        type="button"
                        className="text-[11px] text-brand-primary hover:underline"
                        onClick={() => toggleCategory(cat)}
                      >
                        {allIn ? "Clear group" : "Select all"}
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      {items.map((e) => (
                        <label
                          key={e.key}
                          className="flex items-start gap-2 rounded p-1.5 text-[12px] hover:bg-surface-sunken"
                        >
                          <Checkbox
                            checked={draft.events.includes(e.key)}
                            onCheckedChange={() => toggleEvent(e.key)}
                            className="mt-0.5"
                          />
                          <span>
                            <span className="block font-mono text-[11px] text-brand-primary-dark">{e.key}</span>
                            <span className="block text-[10.5px] text-text-secondary">{e.description}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <Separator />

          <div>
            <Label className="mb-2 block text-[12px] font-semibold">Retry policy</Label>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label className="text-[11px]">Attempts</Label>
                <Input
                  type="number"
                  min={2}
                  max={8}
                  value={draft.retry.attempts}
                  onChange={(e) =>
                    setDraft({ ...draft, retry: { ...draft.retry, attempts: Math.max(2, Math.min(8, +e.target.value)) } })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px]">Backoff</Label>
                <Select
                  value={draft.retry.backoff}
                  onValueChange={(v) => setDraft({ ...draft, retry: { ...draft.retry, backoff: v as "linear" | "exponential" } })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="linear">Linear</SelectItem>
                    <SelectItem value="exponential">Exponential</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px]">Max age (h)</Label>
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
            <div className="mb-2 flex items-center justify-between">
              <Label className="text-[12px] font-semibold">Custom headers</Label>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setDraft({ ...draft, headers: [...draft.headers, { key: "", value: "" }] })
                }
              >
                <Plus className="mr-1 h-3 w-3" /> Add
              </Button>
            </div>
            <div className="space-y-1.5">
              {draft.headers.length === 0 && (
                <p className="text-[11px] text-text-muted">No custom headers.</p>
              )}
              {draft.headers.map((h, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    placeholder="Header"
                    className="font-mono text-[12px]"
                    value={h.key}
                    onChange={(e) => {
                      const next = [...draft.headers];
                      next[i] = { ...next[i], key: e.target.value };
                      setDraft({ ...draft, headers: next });
                    }}
                  />
                  <Input
                    placeholder="Value"
                    className="font-mono text-[12px]"
                    value={h.value}
                    onChange={(e) => {
                      const next = [...draft.headers];
                      next[i] = { ...next[i], value: e.target.value };
                      setDraft({ ...draft, headers: next });
                    }}
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8"
                    onClick={() => setDraft({ ...draft, headers: draft.headers.filter((_, j) => j !== i) })}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="shrink-0 border-t border-[var(--border-token)] px-6 py-3 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
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
