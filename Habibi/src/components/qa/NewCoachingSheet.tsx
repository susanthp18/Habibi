import { useState } from "react";
import { X } from "lucide-react";
import { AGENT_POOL, type CoachingAction } from "@/data/qa-seed";

const CATEGORIES = ["Empathy", "Resolution", "Compliance", "Script Adherence", "Upsell"];

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
  const [due, setDue] = useState(() => new Date(Date.now() + 3 * 86400_000).toISOString().slice(0, 10));

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-md flex-col bg-surface-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border-token)] px-4 py-3">
          <div>
            <div className="text-[15px] font-semibold text-brand-navy">New coaching action</div>
            <div className="text-[11px] text-text-muted">Assignable to any agent — appears on their scorecard.</div>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-surface-sunken">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4 text-[12px]">
          <label className="block">
            <span className="mb-1 block font-medium text-text-secondary">Agent</span>
            <select value={agent} onChange={(e) => setAgent(e.target.value)} className="w-full rounded-md border border-[var(--border-token)] bg-surface-app px-2 py-1.5">
              {AGENT_POOL.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block font-medium text-text-secondary">Focus area</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="w-full rounded-md border border-[var(--border-token)] bg-surface-app px-2 py-1.5">
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block font-medium text-text-secondary">Action title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Read mini-Miranda before dues discussion…" className="w-full rounded-md border border-[var(--border-token)] bg-surface-app px-2 py-1.5" />
          </label>
          <label className="block">
            <span className="mb-1 block font-medium text-text-secondary">Due date</span>
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="w-full rounded-md border border-[var(--border-token)] bg-surface-app px-2 py-1.5" />
          </label>
          {(presetScorecardId || presetCallId) && (
            <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken px-2 py-2 text-[11px] text-text-secondary">
              Linked to {presetScorecardId ? `scorecard ${presetScorecardId}` : `call ${presetCallId}`}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-token)] px-4 py-3">
          <button onClick={onClose} className="rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] hover:bg-surface-sunken">Cancel</button>
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
            className="rounded-md bg-brand-primary px-3 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark disabled:opacity-40"
          >
            Create action
          </button>
        </div>
      </div>
    </div>
  );
}
