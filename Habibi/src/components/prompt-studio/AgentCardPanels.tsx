import { Lozenge } from "@/components/ui/lozenge";
import { gateTone } from "@/lib/gate-status";
import { useCompileCard, type CompileReport } from "@/api/agent-studio";

// The six Agent Card tabs, one file each under ./panels. Re-exported here so
// every existing import path keeps working.
export { ToolsTab } from "./panels/ToolsTab";
export { SkillsTab } from "./panels/SkillsTab";
export { ConnectorsTab } from "./panels/ConnectorsTab";
export { EvalsTab } from "./panels/EvalsTab";
export { AgentGraphTab } from "./panels/AgentGraphTab";
export { PolicyTab } from "./panels/PolicyTab";

export function CompileReportList({ report }: { report: CompileReport | null }) {
  if (!report) return null;
  return (
    <ul className="space-y-050 text-body-small">
      {report.gates.map((g) => (
        <li key={g.gate} className="flex items-start justify-between gap-100">
          <span>
            <span className="font-mono">{g.gate}</span> {g.name}
            {g.detail ? <span className="ml-075 text-text-subtle">{g.detail}</span> : null}
          </span>
          <Lozenge tone={gateTone(g.status)}>{g.status}</Lozenge>
        </li>
      ))}
    </ul>
  );
}

export function useStudioCompile(botId: string) {
  return useCompileCard(botId);
}
