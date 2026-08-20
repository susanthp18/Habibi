import { ChartCard, SegmentedBar, SnapshotPill } from "@/components/charts";

type Props = {
  positive: number;
  neutral: number;
  negative: number;
};

export function SentimentDistribution({ positive, neutral, negative }: Props) {
  const total = positive + neutral + negative || 1;
  const p = (positive / total) * 100;
  const n = (neutral / total) * 100;
  const g = (negative / total) * 100;

  return (
    <ChartCard
      title="Sentiment distribution"
      subtitle="Aggregated across every call in period"
      action={<SnapshotPill />}
    >
      <SegmentedBar
        segments={[
          {
            id: "positive",
            label: "Positive",
            pct: p,
            color: "#5b7f24",
            valueLabel: `${p.toFixed(1)}%`,
            detail: `${positive.toLocaleString()} calls scored positive. Higher share usually tracks with recovery and PTP kept-rate.`,
          },
          {
            id: "neutral",
            label: "Neutral",
            pct: n,
            color: "#e06c00",
            valueLabel: `${n.toFixed(1)}%`,
            detail: `${neutral.toLocaleString()} calls scored neutral — often information-seeking or early-stage conversations.`,
          },
          {
            id: "negative",
            label: "Negative",
            pct: g,
            color: "#e2483d",
            valueLabel: `${g.toFixed(1)}%`,
            detail: `${negative.toLocaleString()} calls scored negative. Watch escalation and compliance for this cohort.`,
          },
        ]}
      />
    </ChartCard>
  );
}
