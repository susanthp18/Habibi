import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import type { CalibrationSession, Rubric, Scorecard } from "@/api/types/qa";
import { useCreateCalibrationSession, useSubmitCalibrationScores } from "@/api/qa";
import { useMe } from "@/api/me";
import type { ScorecardEntry } from "@/api/types/qa";
import { RubricScorer } from "./RubricScorer";
import { useStaff } from "@/api/staff";
import { SelectField } from "@/components/ui/select";
import { computeTotal } from "@/lib/qa";
import { ScoreBand } from "./ScoreBand";

/** The acting reviewer scores the session call; submitted once, every criterion. */
function MyScores({ session, rubric }: { session: CalibrationSession; rubric: Rubric }) {
  const submit = useSubmitCalibrationScores();
  const criteria = rubric.sections.flatMap((s) => s.criteria);
  const [entries, setEntries] = useState<ScorecardEntry[]>(() =>
    criteria.map((c) => ({ criterionId: c.id, aiSuggested: 0, score: 0 })),
  );
  return (
    <div className="space-y-100 border-t border-border p-150">
      <div className="text-body font-semibold text-text">Your scores</div>
      <p className="text-body-small text-text-subtle">
        Score this call against the rubric version the session uses. Your total is compared with the
        target once you submit.
      </p>
      <RubricScorer rubric={rubric} entries={entries} onChange={setEntries} />
      <button
        type="button"
        disabled={submit.isPending}
        onClick={() =>
          submit.mutate({
            sessionId: session.id,
            entries: entries.map((e) => ({ criterionId: e.criterionId, score: e.score })),
          })
        }
        className="rounded-medium bg-background-brand-bold px-150 py-050 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-pressed"
      >
        Submit my scores
      </button>
    </div>
  );
}

/** Open a session over one scored call; its scorecard is the target. */
function NewCalibrationForm({
  scorecards,
  onDone,
}: {
  scorecards: Scorecard[];
  onDone: (session?: CalibrationSession) => void;
}) {
  const { data: staff } = useStaff();
  const create = useCreateCalibrationSession();
  const [callId, setCallId] = useState("");
  const [reviewers, setReviewers] = useState<string[]>([]);
  const scored = scorecards.filter((s) => s.status !== "unscored");
  const humans = (staff ?? []).filter((s) => s.kind === "human");
  const toggle = (id: string) =>
    setReviewers((prev) => (prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]));

  return (
    <div className="space-y-100 rounded-large border border-border bg-surface p-150">
      <div className="text-body font-semibold text-text">New calibration</div>
      <SelectField
        aria-label="Call to calibrate"
        value={callId}
        onChange={setCallId}
        placeholder={scored.length ? "Choose a scored call" : "No scored calls in the queue"}
        disabled={!scored.length}
        options={scored.map((s) => ({
          value: s.callId,
          label: `${s.customerName} · ${s.handledBy.label} · ${s.status === "final" ? "final" : "AI draft"}`,
        }))}
      />
      <div className="text-body-small text-text-subtle">Reviewers</div>
      <div className="flex max-h-40 flex-wrap gap-050 overflow-y-auto">
        {humans.map((u) => (
          <label
            key={u.id}
            className={cn(
              "inline-flex cursor-pointer items-center gap-050 rounded-full border px-100 py-025 text-body-small",
              reviewers.includes(u.id)
                ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                : "border-border text-text-subtle",
            )}
          >
            <input
              type="checkbox"
              className="sr-only"
              checked={reviewers.includes(u.id)}
              onChange={() => toggle(u.id)}
            />
            {u.name}
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-100">
        <button
          onClick={() => onDone()}
          className="rounded-medium border border-border px-150 py-050 text-body-small hover:bg-surface-sunken"
        >
          Cancel
        </button>
        <button
          disabled={!callId || !reviewers.length || create.isPending}
          onClick={() =>
            create.mutate(
              { interactionId: callId, reviewerUserIds: reviewers },
              { onSuccess: (session) => onDone(session) },
            )
          }
          className="rounded-medium bg-background-brand-bold px-150 py-050 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-pressed disabled:opacity-40"
        >
          Open session
        </button>
      </div>
    </div>
  );
}

export function CalibrationView({
  sessions,
  rubricFor,
  scorecards,
  onClose,
}: {
  sessions: CalibrationSession[];
  /** The rubric version a session is scored on. */
  rubricFor: (rubricId?: string | null) => Rubric;
  /** The scoring queue: new sessions pick a scored call from it. */
  scorecards: Scorecard[];
  onClose: (id: string) => void;
}) {
  const [activeId, setActiveId] = useState<string>(sessions[0]?.id ?? "");
  const [creating, setCreating] = useState(false);
  const { data: me } = useMe();
  const active = sessions.find((s) => s.id === activeId) ?? sessions[0];
  const newButton = (
    <button
      onClick={() => setCreating(true)}
      className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
    >
      <Plus className="h-3.5 w-3.5" /> New calibration
    </button>
  );
  const form = creating && (
    <NewCalibrationForm
      scorecards={scorecards}
      onDone={(session) => {
        setCreating(false);
        if (session) setActiveId(session.id);
      }}
    />
  );

  if (!active) {
    return (
      <div className="space-y-150">
        {form}
        <div className="rounded-large border border-border bg-surface p-300 text-center text-body-small text-text-subtlest">
          <div className="mb-100">No calibration sessions.</div>
          {!creating && newButton}
        </div>
      </div>
    );
  }

  const rubric = rubricFor(active.rubricId);
  const targetTotal = computeTotal({ entries: active.target }, rubric);
  const myTurn =
    active.status === "active" &&
    active.reviewers.some((r) => r.reviewer === me?.name && r.submitted === false);

  return (
    <div className="space-y-150">
      {creating ? form : <div className="flex justify-end">{newButton}</div>}
      <div className="grid gap-150 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div className="space-y-050 rounded-large border border-border bg-surface p-100">
          <div className="px-100 pb-050 text-body-small font-semibold text-text-subtlest">
            Sessions
          </div>
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveId(s.id)}
              className={cn(
                "w-full rounded-medium px-100 py-100 text-left text-body-small",
                s.id === active.id
                  ? "bg-background-brand-subtlest text-text-brand"
                  : "hover:bg-surface-sunken text-text",
              )}
            >
              <div className="font-medium">{s.name}</div>
              <div className="text-body-small text-text-subtlest">
                {s.customerName} · {s.reviewers.length} reviewers · {s.status}
              </div>
            </button>
          ))}
        </div>

        <div className="rounded-large border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-150 py-100">
            <div>
              <div className="text-body font-semibold text-text">{active.name}</div>
              <div className="text-body-small text-text-subtlest">
                Target score for {active.customerName}: <ScoreBand total={targetTotal} size="sm" />
              </div>
            </div>
            {active.status === "active" && (
              <button
                onClick={() => {
                  onClose(active.id);
                  toast.success("Calibration closed", { description: active.name });
                }}
                className="rounded-medium bg-background-brand-bold px-150 py-050 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-pressed"
              >
                Close variance
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-body-small">
              <thead className="bg-surface-sunken text-body-small text-text-subtlest">
                <tr>
                  <th className="px-150 py-100 text-left font-medium">Reviewer</th>
                  {rubric.sections.map((s) => (
                    <th key={s.id} className="px-150 py-100 text-left font-medium">
                      {s.label}
                    </th>
                  ))}
                  <th className="px-150 py-100 text-right font-medium">Total</th>
                  <th className="px-150 py-100 text-right font-medium">Δ vs target</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <tr className="bg-background-brand-subtlest/40">
                  <td className="px-150 py-100 font-semibold text-text">Target</td>
                  {rubric.sections.map((s) => {
                    const sub = computeTotal(
                      {
                        entries: active.target.filter((e) =>
                          s.criteria.some((c) => c.id === e.criterionId),
                        ),
                      },
                      { ...rubric, sections: [s] },
                    );
                    return (
                      <td key={s.id} className="px-150 py-100 text-text">
                        {sub.toFixed(0)}
                      </td>
                    );
                  })}
                  <td className="px-150 py-100 text-right">
                    <ScoreBand total={targetTotal} size="sm" />
                  </td>
                  <td className="px-150 py-100 text-right text-text-subtlest">—</td>
                </tr>
                {active.reviewers.map((r) => {
                  if (r.submitted === false) {
                    return (
                      <tr key={r.reviewer}>
                        <td className="px-150 py-100 font-medium text-text">{r.reviewer}</td>
                        <td
                          colSpan={rubric.sections.length + 2}
                          className="px-150 py-100 text-text-subtlest"
                        >
                          Awaiting scores
                        </td>
                      </tr>
                    );
                  }
                  const total = computeTotal({ entries: r.entries }, rubric);
                  const delta = total - targetTotal;
                  const bad = Math.abs(delta) > 8;
                  return (
                    <tr key={r.reviewer}>
                      <td className="px-150 py-100 font-medium text-text">{r.reviewer}</td>
                      {rubric.sections.map((s) => {
                        const sub = computeTotal(
                          {
                            entries: r.entries.filter((e) =>
                              s.criteria.some((c) => c.id === e.criterionId),
                            ),
                          },
                          { ...rubric, sections: [s] },
                        );
                        return (
                          <td key={s.id} className="px-150 py-100 text-text">
                            {sub.toFixed(0)}
                          </td>
                        );
                      })}
                      <td className="px-150 py-100 text-right">
                        <ScoreBand total={total} size="sm" />
                      </td>
                      <td
                        className={cn(
                          "px-150 py-100 text-right font-medium",
                          bad ? "text-text-danger-bolder" : "text-text-success-bolder",
                        )}
                      >
                        {delta > 0 ? "+" : ""}
                        {delta.toFixed(1)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {myTurn && <MyScores key={active.id} session={active} rubric={rubric} />}
        </div>
      </div>
    </div>
  );
}
