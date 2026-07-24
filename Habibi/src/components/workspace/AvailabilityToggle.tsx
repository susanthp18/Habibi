import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  presenceToUi,
  uiToPresence,
  usePatchPresence,
  usePresence,
  type AvailabilityUi,
} from "@/api/presence";

const options: {
  key: AvailabilityUi;
  label: string;
  dot: string;
  ring: string;
  text: string;
  bg: string;
}[] = [
  {
    key: "available",
    label: "Available",
    dot: "bg-success",
    ring: "pulse-dot",
    text: "text-success",
    bg: "bg-success-bg",
  },
  {
    key: "break",
    label: "On break",
    dot: "bg-warning",
    ring: "",
    text: "text-warning",
    bg: "bg-warning-bg",
  },
  {
    key: "wrap",
    label: "Wrap-up",
    dot: "bg-info",
    ring: "",
    text: "text-info",
    bg: "bg-brand-tint",
  },
];

export function AvailabilityToggle() {
  const { data } = usePresence();
  const mutation = usePatchPresence();
  const status = presenceToUi(data?.status);
  const active = options.find((o) => o.key === status)!;

  const setStatus = (next: AvailabilityUi) => {
    if (next === status || mutation.isPending) return;
    const label = options.find((o) => o.key === next)?.label ?? next;
    mutation.mutate(uiToPresence(next), {
      onSuccess: () => toast.success(`Status · ${label}`),
      onError: (e: unknown) =>
        toast.error(e instanceof Error ? e.message : "Could not update availability"),
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <div
        className={cn(
          "inline-flex items-center gap-2 rounded-md border px-2.5 py-1.5",
          active.bg,
          status === "available" && "border-success/25",
          status === "break" && "border-warning/30",
          status === "wrap" && "border-brand-primary/20",
        )}
      >
        <span className={cn("h-2 w-2 rounded-full", active.dot, active.ring)} />
        <span className={cn("text-[12px] font-semibold", active.text)}>{active.label}</span>
      </div>
      <div className="inline-flex rounded-md border border-[var(--border-token)] bg-surface-card p-0.5 shadow-sm">
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            disabled={mutation.isPending}
            onClick={() => setStatus(o.key)}
            className={cn(
              "rounded-[5px] px-3 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-60",
              status === o.key
                ? "bg-brand-primary text-white shadow-sm"
                : "text-text-secondary hover:bg-surface-sunken",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
