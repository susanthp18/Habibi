import type {
  AgentQaStat,
  CoachingAction,
  Rubric,
  RubricCriterion,
  RubricSection,
  ScoreBand,
  Scorecard,
  ScorecardEntry,
} from "@/api/types/qa";

export function allCriteria(rubric: Rubric): RubricCriterion[] {
  return rubric.sections.flatMap((s) => s.criteria);
}

export function sectionTotal(section: RubricSection, entries: ScorecardEntry[]): number {
  const weightSum = section.criteria.reduce((a, c) => a + c.weight, 0) || 1;
  let acc = 0;
  for (const c of section.criteria) {
    const e = entries.find((x) => x.criterionId === c.id);
    const score = e?.score ?? 0;
    acc += (score / 5) * (c.weight / weightSum);
  }
  return acc * 100; // 0..100 within section
}

// Takes only what it reads. Typed as a whole Scorecard, every caller that
// scored a subset of entries — the calibration table scores each section
// separately — had to `as any` a two-field object past the signature, which
// silenced the check for the field it does use as well.
export function computeTotal(sc: Pick<Scorecard, "entries">, rubric: Rubric): number {
  // Critical-fail: any critical criterion with score 0 caps total at 40.
  const hasCriticalZero = rubric.sections.some((s) =>
    s.criteria.some(
      (c) => c.critical && (sc.entries.find((e) => e.criterionId === c.id)?.score ?? 0) === 0,
    ),
  );
  const weightSum = rubric.sections.reduce((a, s) => a + s.weight, 0) || 1;
  const total = rubric.sections.reduce(
    (acc, s) => acc + (sectionTotal(s, sc.entries) * s.weight) / weightSum,
    0,
  );
  return hasCriticalZero ? Math.min(total, 40) : total;
}

export function bandFor(total: number): ScoreBand {
  if (total >= 85) return "green";
  if (total >= 70) return "amber";
  return "red";
}

export function bandColor(band: ScoreBand): { text: string; bg: string; border: string } {
  if (band === "green")
    return {
      text: "text-text-success-bolder",
      bg: "bg-background-success-subtler",
      border: "border-border-success-subtle",
    };
  if (band === "amber")
    return {
      text: "text-text-warning-bolder",
      bg: "bg-background-warning-subtler",
      border: "border-border-warning-subtle",
    };
  return {
    text: "text-text-danger-bolder",
    bg: "bg-background-danger-subtler",
    border: "border-border-danger-subtle",
  };
}

// ---------- agent stats ----------

export function agentStats(
  all: Scorecard[],
  rubric: Rubric,
  coaching: CoachingAction[],
): AgentQaStat[] {
  const byAgent = new Map<string, Scorecard[]>();
  for (const s of all) {
    if (s.status === "unscored") continue;
    const arr = byAgent.get(s.agentId) ?? [];
    arr.push(s);
    byAgent.set(s.agentId, arr);
  }
  const out: AgentQaStat[] = [];
  for (const [agentId, cards] of byAgent.entries()) {
    const totals = cards.map((c) => computeTotal(c, rubric));
    const avg = totals.reduce((a, b) => a + b, 0) / (totals.length || 1);
    const half = Math.max(1, Math.floor(cards.length / 2));
    const recent = totals.slice(0, half).reduce((a, b) => a + b, 0) / half;
    const prior = totals.slice(half).reduce((a, b) => a + b, 0) / Math.max(1, totals.length - half);
    const sectionScores = rubric.sections.map((s) => {
      const vals = cards.map((c) => sectionTotal(s, c.entries));
      return { section: s.label, value: vals.reduce((a, b) => a + b, 0) / (vals.length || 1) };
    });
    const weakest = sectionScores.slice().sort((a, b) => a.value - b.value)[0]?.section ?? "—";
    // cards arrive newest first; the sparkline reads oldest to newest
    const trend = totals.slice(0, 7).reverse();
    out.push({
      agentId,
      isBot: cards.some((c) => c.handledBy.kind === "bot"),
      scored: cards.length,
      avg,
      delta7d: recent - prior,
      band: bandFor(avg),
      weakestSection: weakest,
      openCoaching: coaching.filter((c) => c.agentId === agentId && c.status !== "done").length,
      trend,
      sectionScores,
    });
  }
  return out.sort((a, b) => b.avg - a.avg);
}
