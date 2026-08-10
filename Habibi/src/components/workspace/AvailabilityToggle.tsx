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
    dot: "bg-background-success",
    ring: "pulse-dot",
    text: "text-text-success",
    bg: "bg-background-success",
  },
  {
    key: "break",
    label: "On break",
    dot: "bg-background-warning",
    ring: "",
    text: "text-text-warning",
    bg: "bg-background-warning",
  },
  {
    key: "wrap",
    label: "Wrap-up",
    dot: "bg-background-information-bold",
    ring: "",
    text: "text-text-information",
    bg: "bg-background-information",
  },
];

const offlineOption = {
  key: "offline" as const,
  label: "Offline",
  dot: "bg-text-subtlest",
  ring: "",
  text: "text-text-subtlest",
  bg: "bg-surface-sunken",
};

export function AvailabilityToggle() {
  const { data } = usePresence();
  const mutation = usePatchPresence();
  const status = presenceToUi(data?.status);
  const active = options.find((o) => o.key === status) ?? offlineOption;

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
    <div className="flex flex-wrap items-center gap-150">
      <div
        className={cn(
          "inline-flex items-center gap-100 rounded-medium border px-150 py-075",
          active.bg,
          status === "available" && "border-border-success/25",
          status === "break" && "border-border-warning/30",
          status === "wrap" && "border-border-information/20",
          status === "offline" && "border-border",
        )}
      >
        <span className={cn("h-100 w-100 rounded-full", active.dot, active.ring)} />
        <span className={cn("text-body-small font-medium", active.text)}>
          {active.label}
        </span>
      </div>
      <div
        className="inline-flex rounded-medium border border-border bg-surface p-025"
        role="group"
        aria-label="Availability"
      >
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            aria-pressed={status === o.key}
            disabled={mutation.isPending}
            onClick={() => setStatus(o.key)}
            className={cn(
              "rounded-medium px-150 py-075 text-body-small font-medium transition-colors disabled:opacity-60",
              status === o.key
                ? "bg-background-brand-bold text-text-inverse"
                : "text-text-subtle hover:bg-surface-sunken",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
