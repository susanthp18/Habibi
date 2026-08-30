import { ChartCard, ChartStage, ModernBars, SnapshotPill } from "@/components/charts";

export function CardSkillAnalytics({
  byCard = [],
  skillHistogram = [],
}: {
  byCard?: Array<{
    botId: string;
    sessions: number;
    contained: number;
    escalated: number;
    containment: number;
    handoffRate: number;
    latencyP99: number;
    sloMs: number;
  }>;
  skillHistogram?: Array<{ skillId: string; activations: number }>;
}) {
  const skillData = skillHistogram.map((s) => ({
    label: s.skillId,
    value: s.activations,
    color: "#5b7f24",
  }));

  return (
    <div className="grid gap-200 xl:grid-cols-2">
      <ChartCard
        title="Per card"
        subtitle="Containment, handoff rate, p99 vs 800 ms SLO"
        action={<SnapshotPill />}
      >
        <div className="overflow-x-auto p-150">
          {byCard.length === 0 ? (
            <p className="text-body-small text-text-subtlest">
              No card-attributed sessions in this window.
            </p>
          ) : (
            <table className="w-full text-body-small">
              <thead className="text-text-subtle">
                <tr>
                  <th className="py-050 text-left font-medium">Card</th>
                  <th className="py-050 text-right font-medium">Sessions</th>
                  <th className="py-050 text-right font-medium">Contain</th>
                  <th className="py-050 text-right font-medium">Handoff</th>
                  <th className="py-050 text-right font-medium">p99</th>
                </tr>
              </thead>
              <tbody>
                {byCard.map((row) => (
                  <tr key={row.botId} className="border-t border-border">
                    <td className="py-075 font-mono text-body-tiny">{row.botId}</td>
                    <td className="py-075 text-right tabular">{row.sessions}</td>
                    <td className="py-075 text-right tabular">{row.containment.toFixed(1)}%</td>
                    <td className="py-075 text-right tabular">{row.handoffRate.toFixed(1)}%</td>
                    <td
                      className={`py-075 text-right tabular ${row.latencyP99 > row.sloMs ? "text-text-danger" : "text-text"}`}
                    >
                      {Math.round(row.latencyP99)}ms
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </ChartCard>
      <ChartCard
        title="Skill activation"
        subtitle="bot_tool_calls.skill_id this window"
        action={<SnapshotPill />}
      >
        <ChartStage>
          <div className="min-h-[14rem] p-150">
            {skillData.length === 0 ? (
              <p className="text-body-small text-text-subtlest">No skill activations recorded.</p>
            ) : (
              <ModernBars data={skillData} height={200} />
            )}
          </div>
        </ChartStage>
      </ChartCard>
    </div>
  );
}
