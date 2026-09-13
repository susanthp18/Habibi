import { useState } from "react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import {
  fetchTwinCorpus,
  runBounceTwin,
  useGrowTwinCorpus,
  type TwinRunResult,
} from "@/api/sandbox";
import { Button } from "@/components/ui/button";

export function TwinTab() {
  const [run, setRun] = useState<TwinRunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const corpus = useQuery({
    queryKey: ["twin-corpus"],
    queryFn: fetchTwinCorpus,
  });
  const grow = useGrowTwinCorpus();

  const replay = async () => {
    setBusy(true);
    try {
      const next = await runBounceTwin();
      setRun(next);
      toast.success(next.grader.passed ? "Twin ladder passed" : "Twin ladder failed");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Twin run failed");
    } finally {
      setBusy(false);
    }
  };

  const wa = run?.outcome.queues?.whatsapp?.length ?? 0;
  const voice = run?.outcome.queues?.voice?.length ?? 0;
  const rows = corpus.data ?? [];
  const corpusUnknown = corpus.isError;

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Replay a bounce chase against the fake ledger. The twin never dials. Corpus grows from kept
        PTPs — never raw audio.
      </p>
      <div className="flex flex-wrap gap-075">
        <Button type="button" size="sm" disabled={busy} onClick={() => void replay()}>
          {busy ? "Running…" : "Replay bounce ladder"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={grow.isPending}
          onClick={() => void grow.mutateAsync()}
        >
          {grow.isPending ? "Growing…" : "Grow from kept PTPs"}
        </Button>
      </div>
      {run ? (
        <dl className="space-y-075 text-body-small">
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtlest">Grader</dt>
            <dd className="font-semibold text-text">{run.grader.passed ? "pass" : "fail"}</dd>
          </div>
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtlest">WhatsApp queue</dt>
            <dd className="tabular text-text">{wa}</dd>
          </div>
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtlest">Voice queue</dt>
            <dd className="tabular text-text">{voice}</dd>
          </div>
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtlest">Dialled</dt>
            <dd className="text-text">{run.outcome.dialled ? "yes" : "no"}</dd>
          </div>
        </dl>
      ) : null}
      <div>
        <div className="mb-075 text-body-small font-semibold text-text">Twin corpus</div>
        <ul className="divide-y divide-border rounded-medium border border-border">
          {corpusUnknown ? (
            <li className="px-150 py-100 text-body-tiny text-text-danger">
              The twin corpus could not be read.
            </li>
          ) : rows.length === 0 ? (
            <li className="px-150 py-100 text-body-tiny text-text-subtlest">
              No outcome tasks yet.
            </li>
          ) : (
            rows.map((r) => (
              <li key={r.id} className="px-150 py-075 text-body-tiny">
                <div className="font-medium text-text">{r.source}</div>
                <div className="font-mono text-text-subtle">{r.sourceRef}</div>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
