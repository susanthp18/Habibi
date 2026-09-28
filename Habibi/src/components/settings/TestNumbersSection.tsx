/** Test numbers: the handsets test calls may ring, and the engine's own test allow-list. */
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useTestCallOptions, useTestNumberMutations } from "@/api/platform";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { QueryErrorBanner } from "@/components/ui/query-state";

export function TestNumbersSection() {
  const options = useTestCallOptions();
  const { add, remove } = useTestNumberMutations();
  const [e164, setE164] = useState("");
  const [label, setLabel] = useState("");

  const onAdd = async () => {
    try {
      await add.mutateAsync({ e164: e164.trim(), label: label.trim() || undefined });
      setE164("");
      setLabel("");
      toast.success("Test number added");
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <section>
      <h2 className="text-body font-semibold">Test numbers</h2>
      <p className="mb-200 mt-025 max-w-3xl text-body-small text-text-subtle">
        Handsets your team holds. Test calls ring only these, and Voice Studio's own editor test
        calls may reach only these or real customers through the contact policy. A number that
        matches a customer on file gives the agent that customer's account.
      </p>
      <div className="max-w-3xl space-y-150">
        {options.isPending ? (
          <LoadingState label="Loading test numbers" />
        ) : options.isError ? (
          <QueryErrorBanner label="test numbers" error={options.error} />
        ) : options.data.numbers.length === 0 ? (
          <p className="text-body-small text-text-subtlest">No test numbers yet.</p>
        ) : (
          <ul className="divide-y divide-border rounded-medium border border-border">
            {options.data.numbers.map((n) => (
              <li key={n.id} className="flex items-center justify-between gap-150 px-150 py-100">
                <div className="min-w-0 text-body-small">
                  <span className="font-mono text-text">{n.e164}</span>
                  {n.label ? <span className="ml-100 text-text-subtle">{n.label}</span> : null}
                  <div className="text-text-subtlest">
                    {n.customer ? `Customer on file: ${n.customer.name}` : "No customer on file"}
                  </div>
                </div>
                <div className="flex items-center gap-100">
                  {n.blocked ? <Lozenge tone="danger">Blocked: {n.blocked}</Lozenge> : null}
                  <Button
                    variant="subtle"
                    aria-label={`Remove ${n.e164}`}
                    disabled={remove.isPending}
                    onClick={() =>
                      void remove
                        .mutateAsync(n.id)
                        .then(() => toast.info("Test number removed"))
                        .catch((err: Error) => toast.error(err.message))
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-end gap-100">
          <Input
            aria-label="Phone number with country code"
            placeholder="+91 98765 43210"
            value={e164}
            onChange={(e) => setE164(e.target.value)}
            className="w-56"
          />
          <Input
            aria-label="Label"
            placeholder="Whose handset (optional)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-64"
          />
          <Button onClick={() => void onAdd()} disabled={!e164.trim() || add.isPending}>
            Add number
          </Button>
        </div>
      </div>
    </section>
  );
}
