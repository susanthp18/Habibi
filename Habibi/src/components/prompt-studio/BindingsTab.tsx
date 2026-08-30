// -----------------------------------------------------------------------------
// Provider bindings — which STT / TTS / LLM this card actually runs on.
//
// GET/POST/DELETE /providers/bindings have been served since the registry went
// multi-vendor and no screen has ever called them, so the only way to move a
// card off Azure was a curl command.
//
// The endpoint returns two different kinds of row and they must not read alike:
// a binding scoped to this bot, and a tenant default the bot inherits
// (`bot_id IS NULL`). Deleting an inherited row changes every card in the
// tenant. The table says which is which, and the delete button says so too.
// -----------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { AlertCircle, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  providerDot,
  useDeleteBinding,
  useProviderBindings,
  useProviderModels,
  useUpsertBinding,
  type ProviderBinding,
  type ProviderSlot,
} from "@/api/providers";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const SLOTS: ProviderSlot[] = ["stt", "tts", "llm"];
const SLOT_LABEL: Record<ProviderSlot, string> = {
  stt: "Speech to text",
  tts: "Text to speech",
  llm: "Language model",
};

function AddBindingRow({ botId, onDone }: { botId: string; onDone: () => void }) {
  const [slot, setSlot] = useState<ProviderSlot>("tts");
  const [modelId, setModelId] = useState<string>("");
  const [locale, setLocale] = useState<string>("");
  const [priority, setPriority] = useState<string>("100");
  const models = useProviderModels(slot);
  const upsert = useUpsertBinding(botId);

  const priorityNum = Number(priority);
  // The server enforces 1..1000; saying so here beats a 422 the author has to
  // decode after losing the rest of the form.
  const priorityValid = Number.isInteger(priorityNum) && priorityNum >= 1 && priorityNum <= 1000;
  const canSave = Boolean(modelId) && priorityValid && !upsert.isPending;

  const save = () => {
    upsert.mutate(
      {
        slot,
        providerModelId: modelId,
        botId,
        locale: locale.trim() || null,
        priority: priorityNum,
      },
      {
        onSuccess: () => {
          toast.success(`Bound ${SLOT_LABEL[slot].toLowerCase()} for this card`);
          onDone();
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not save binding"),
      },
    );
  };

  return (
    <div className="rounded-medium border border-border bg-surface-sunken/40 p-150">
      <div className="grid grid-cols-1 gap-100 md:grid-cols-[140px_minmax(0,1fr)_120px_100px_auto] md:items-end">
        <label className="text-body-small">
          <span className="mb-050 block text-text-subtlest">Slot</span>
          <Select value={slot} onValueChange={(v) => setSlot(v as ProviderSlot)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SLOTS.map((s) => (
                <SelectItem key={s} value={s}>
                  {SLOT_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="text-body-small">
          <span className="mb-050 block text-text-subtlest">Model</span>
          <Select value={modelId} onValueChange={setModelId}>
            <SelectTrigger>
              <SelectValue placeholder={models.isPending ? "Loading models…" : "Pick a model"} />
            </SelectTrigger>
            <SelectContent>
              {(models.data ?? []).map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.providerName} · {m.displayName}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="text-body-small">
          <span className="mb-050 block text-text-subtlest">Locale</span>
          <Input
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
            placeholder="any"
            aria-label="Locale"
          />
        </label>
        <label className="text-body-small">
          <span className="mb-050 block text-text-subtlest">Priority</span>
          <Input
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            inputMode="numeric"
            aria-label="Priority"
            className={cn(!priorityValid && "border-border-danger")}
          />
        </label>
        <div className="flex gap-075">
          <Button size="sm" onClick={save} disabled={!canSave}>
            {upsert.isPending ? "Saving…" : "Save"}
          </Button>
          <Button size="sm" variant="outline" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </div>
      {models.isError && (
        <p className="mt-100 text-body-small text-text-danger">
          Model catalog unavailable — cannot offer a model that may not exist.
        </p>
      )}
      {!priorityValid && (
        <p className="mt-100 text-body-small text-text-danger">Priority must be 1–1000.</p>
      )}
      <p className="mt-100 text-body-small text-text-subtlest">
        Saving replaces any existing binding for the same slot, locale and priority on this card.
      </p>
    </div>
  );
}

function BindingRow({
  binding,
  botId,
  onEdit,
}: {
  binding: ProviderBinding;
  botId: string;
  onEdit: (b: ProviderBinding) => void;
}) {
  const inherited = binding.botId === null;
  const remove = useDeleteBinding(botId);

  const del = () => {
    remove.mutate(binding.id, {
      onSuccess: () => toast.success("Binding removed"),
      onError: (e) => toast.error(e instanceof Error ? e.message : "Could not remove binding"),
    });
  };

  return (
    <tr className={cn(inherited && "bg-surface-sunken/30")}>
      <td className="px-150 py-100">
        <span className="font-medium text-text">{SLOT_LABEL[binding.slot]}</span>
      </td>
      <td className="px-150 py-100">
        <div className="flex items-center gap-075">
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: providerDot(binding.providerId) }}
          />
          <span className="truncate text-text">{binding.providerName}</span>
          <span className="truncate font-mono text-text-subtle">{binding.displayName}</span>
        </div>
      </td>
      <td className="px-150 py-100 font-mono text-text-subtle">{binding.locale ?? "any"}</td>
      <td className="px-150 py-100 font-mono text-text-subtle">{binding.voiceRef ?? "—"}</td>
      <td className="px-150 py-100 text-right font-mono tabular-nums text-text-subtle">
        {binding.priority}
      </td>
      <td className="px-150 py-100">
        {inherited ? (
          <Lozenge tone="information">Tenant default</Lozenge>
        ) : (
          <Lozenge tone="neutral">This card</Lozenge>
        )}
      </td>
      <td className="px-150 py-100">
        {binding.enabled ? (
          <Lozenge tone="success">Enabled</Lozenge>
        ) : (
          <Lozenge tone="warning">Disabled</Lozenge>
        )}
      </td>
      <td className="px-150 py-100 text-right">
        <div className="flex justify-end gap-050">
          <Button size="sm" variant="outline" onClick={() => onEdit(binding)}>
            Edit
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={del}
            disabled={remove.isPending}
            // An inherited row belongs to the tenant, not to this card. The
            // endpoint would happily delete it and every other card would
            // silently change provider.
            title={
              inherited
                ? "Inherited from the tenant — removing it affects every card"
                : "Remove this binding"
            }
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </td>
    </tr>
  );
}

export function BindingsTab({ botId }: { botId: string }) {
  const { data, isPending, isError, error } = useProviderBindings(botId);
  const [adding, setAdding] = useState(false);

  const rows = useMemo(() => data ?? [], [data]);
  const ownRows = rows.filter((b) => b.botId !== null);

  if (isPending) {
    return (
      <div className="px-150 py-200">
        <LoadingState label="Loading provider bindings" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-100 rounded-medium border border-border bg-surface px-150 py-100 text-body-small text-text-danger">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <span>
          Could not load bindings — this card&apos;s providers cannot be confirmed.{" "}
          {(error as Error)?.message ?? ""}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-150">
      <div className="flex flex-wrap items-center gap-100">
        <h2 className="text-body font-semibold text-text">Provider bindings</h2>
        <span className="text-body-small text-text-subtle">
          {ownRows.length} on this card · {rows.length - ownRows.length} inherited
        </span>
        <Button size="sm" className="ml-auto" onClick={() => setAdding(true)} disabled={adding}>
          <Plus className="h-3.5 w-3.5" /> Add binding
        </Button>
      </div>

      {adding && <AddBindingRow botId={botId} onDone={() => setAdding(false)} />}

      {rows.length === 0 ? (
        <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-250 text-center">
          <div className="text-body font-medium text-text">No bindings resolved</div>
          <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">
            This card has no bindings of its own and inherits no tenant defaults, so the runtime
            falls back to whatever the registry defaults to. Add one to make the choice explicit.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-medium border border-border bg-surface">
          <table className="w-full text-body-small">
            <thead>
              <tr className="border-b border-border text-text-subtlest">
                <th className="px-150 py-100 text-left font-semibold">Slot</th>
                <th className="px-150 py-100 text-left font-semibold">Model</th>
                <th className="px-150 py-100 text-left font-semibold">Locale</th>
                <th className="px-150 py-100 text-left font-semibold">Voice</th>
                <th className="px-150 py-100 text-right font-semibold">Priority</th>
                <th className="px-150 py-100 text-left font-semibold">Scope</th>
                <th className="px-150 py-100 text-left font-semibold">State</th>
                <th className="px-150 py-100 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((b) => (
                <BindingRow key={b.id} binding={b} botId={botId} onEdit={() => setAdding(true)} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-body-small leading-relaxed text-text-subtlest">
        The runtime resolves a slot most-specific-first: a binding for this card and locale beats
        one for this card, which beats a tenant default. Ties break on the lower priority number.
      </p>
    </div>
  );
}
