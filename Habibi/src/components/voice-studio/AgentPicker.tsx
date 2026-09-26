import { useEffect } from "react";

import { useStudioAgents } from "@/api/voice-studio";
import { QueryState } from "@/components/ui/query-state";
import { SelectField } from "@/components/ui/select";

/** Pick a Voice Studio agent; selects the first one when nothing is chosen yet. */
export function AgentPicker({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (id: number) => void;
}) {
  const agents = useStudioAgents();
  const list = agents.data ?? [];
  const first = list[0];
  useEffect(() => {
    if (value === null && first) onChange(first.id);
  }, [value, first, onChange]);

  return (
    <QueryState
      query={agents}
      label="agents"
      empty={
        list.length === 0 ? (
          <p className="text-body-small text-text-subtle">
            No agents yet. Create one under Agents.
          </p>
        ) : null
      }
    >
      {list.length > 0 && (
        <SelectField
          aria-label="Agent"
          value={value === null ? "" : String(value)}
          onChange={(v) => onChange(Number(v))}
          className="w-[20rem]"
          options={list.map((a) => ({ value: String(a.id), label: a.name }))}
        />
      )}
    </QueryState>
  );
}
