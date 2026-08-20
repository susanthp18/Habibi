import { LivelineSpark } from "@/components/charts";
import { cn } from "@/lib/utils";

type Props = {
  data: number[];
  width?: number;
  height?: number;
  stroke?: string;
  fill?: string;
  className?: string;
};

/** Resolve design-token colors to hex for canvas rendering. */
function resolveStroke(stroke: string) {
  if (stroke.startsWith("#")) return stroke;
  if (stroke.includes("brand")) return "#1868db";
  if (stroke.includes("success") || stroke.includes("emerald")) return "#5b7f24";
  if (stroke.includes("warning") || stroke.includes("amber")) return "#e06c00";
  if (stroke.includes("danger") || stroke.includes("red")) return "#e2483d";
  return "#1868db";
}

export function Sparkline({
  data,
  width,
  height = 32,
  stroke = "var(--background-brand-bold)",
  className,
}: Props) {
  if (!data.length) return null;
  return (
    <LivelineSpark
      data={data}
      height={height}
      color={resolveStroke(stroke)}
      className={cn(className)}
      style={width ? { width } : undefined}
    />
  );
}
