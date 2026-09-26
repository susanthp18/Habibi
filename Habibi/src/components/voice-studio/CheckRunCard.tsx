import type { CheckRun } from "@/api/voice-studio";

/** One check run: pass/fail per scenario, flags, and the conversation turn by turn. */
export function CheckRunCard({ run, open = false }: { run: CheckRun; open?: boolean }) {
  return (
    <li className="rounded-medium border border-border">
      <details open={open}>
        <summary className="flex cursor-pointer items-center justify-between gap-200 p-150">
          <span className="text-body font-semibold text-text">
            {new Date(run.createdAt).toLocaleString()}
          </span>
          <span className="text-body-small text-text-subtle">
            {run.status === "running" ? "Running…" : `${run.passed} passed · ${run.failed} failed`}
          </span>
        </summary>
        <div className="space-y-200 border-t border-border p-150">
          {run.results.map((res) => (
            <div key={res.scenarioId} className="space-y-100">
              <p className="text-body font-semibold text-text">
                {res.passed ? "Pass" : "Fail"} · {res.scenarioName}
              </p>
              {res.error && <p className="text-body-small text-text-danger">{res.error}</p>}
              {res.flags.length > 0 && (
                <p className="text-body-small text-text-danger">Flags: {res.flags.join(", ")}</p>
              )}
              <ol className="space-y-050">
                {res.turns.map((t, i) => (
                  <li key={i} className="text-body-small">
                    {t.customer && <p className="text-text-subtle">Customer: {t.customer}</p>}
                    <p className={t.flags.length ? "text-text-danger" : "text-text"}>
                      Agent: {t.agent || "(no reply)"}
                      {t.flags.length > 0 && ` — ${t.flags.join(", ")}`}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </details>
    </li>
  );
}
