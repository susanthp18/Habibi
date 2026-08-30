import { useState } from "react";
import { X } from "lucide-react";
import { AGENT_POOL, type CoachingAction } from "@/data/qa-seed";

const CATEGORIES = ["Empathy", "Resolution", "Compliance", "Script adherence", "Upsell"];

export function NewCoachingSheet({
  open,
  onClose,
  onSubmit,
  presetAgent,
  presetScorecardId,
  presetCallId,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (a: Omit<CoachingAction, "id" | "createdAt" | "notes" | "status">) => void;
  presetAgent?: string;
  presetScorecardId?: string;
  presetCallId?: string;
}) {
  const [agent, setAgent] = useState(presetAgent ?? AGENT_POOL[0]!);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0]!);
  const [due, setDue] = useState(() =>
    new Date(Date.now() + 3 * 86400_000).toISOString().slice(0, 10),
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-md flex-col bg-surface shadow-overlay"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-200 py-150">
          <div>
            <div className="text-body font-semibold text-text">New coaching action</div>
            <div className="text-body-small text-text-subtlest">
              Assignable to any agent — appears on their scorecard.
            </div>
          </div>
          <button onClick={onClose} className="rounded p-050 hover:bg-surface-sunken">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-150 overflow-y-auto p-200 text-body-small">
          <label className="block">
            <span className="mb-050 block font-medium text-text-subtle">Agent</span>
            <select
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
              className="w-full rounded-medium border border-border bg-surface px-100 py-075"
            >
              {AGENT_POOL.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-050 block font-medium text-text-subtle">Focus area</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-medium border border-border bg-surface px-100 py-075"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-050 block font-medium text-text-subtle">Action title</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Read mini-Miranda before dues discussion…"
              className="w-full rounded-medium border border-border bg-surface px-100 py-075"
            />
          </label>
          <label className="block">
            <span className="mb-050 block font-medium text-text-subtle">Due date</span>
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="w-full rounded-medium border border-border bg-surface px-100 py-075"
            />
          </label>
          {(presetScorecardId || presetCallId) && (
            <div className="rounded-medium border border-border bg-surface-sunken px-100 py-100 text-body-small text-text-subtle">
              Linked to{" "}
              {presetScorecardId ? `scorecard ${presetScorecardId}` : `call ${presetCallId}`}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-100 border-t border-border px-200 py-150">
          <button
            onClick={onClose}
            className="rounded-medium border border-border px-150 py-075 text-body-small hover:bg-surface-sunken"
          >
            Cancel
          </button>
          <button
            disabled={!title.trim()}
            onClick={() => {
              onSubmit({
                agentId: agent,
                title: title.trim(),
                category,
                dueAt: new Date(due).toISOString(),
                scorecardId: presetScorecardId,
                callId: presetCallId,
              });
            }}
            className="rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed disabled:opacity-40"
          >
            Create action
          </button>
        </div>
      </div>
    </div>
  );
}
