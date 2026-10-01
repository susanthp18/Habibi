import * as RadioGroup from "@radix-ui/react-radio-group";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  presenceToUi,
  uiToPresence,
  usePatchPresence,
  usePresence,
  type AvailabilityUi,
} from "@/api/presence";

const options: { key: AvailabilityUi; label: string; dot: string; text: string; bg: string }[] = [
  {
    key: "available",
    label: "Available",
    dot: "bg-background-success-bold pulse-dot",
    text: "text-text-success",
    bg: "bg-background-success border-border-success/25",
  },
  {
    key: "break",
    label: "On break",
    dot: "bg-background-warning-bold",
    text: "text-text-warning",
    bg: "bg-background-warning border-border-warning/30",
  },
  {
    key: "wrap",
    label: "Wrap-up",
    dot: "bg-background-information-bold",
    text: "text-text-information",
    bg: "bg-background-information border-border-information/20",
  },
  {
    key: "offline",
    label: "Offline",
    dot: "bg-text-subtlest",
    text: "text-text-subtlest",
    bg: "bg-surface-sunken border-border",
  },
];

/** The operator's presence. Reading it never sets it: someone who has not
 *  chosen a status is Offline, and a failed read says so instead of showing
 *  Available. */
export function AvailabilityToggle() {
  const presence = usePresence();
  const mutation = usePatchPresence();
  const status = presence.data ? presenceToUi(presence.data.status) : null;
  const active = options.find((o) => o.key === status);

  const setStatus = (next: string) => {
    if (next === status || mutation.isPending) return;
    const key = next as AvailabilityUi;
    const label = options.find((o) => o.key === key)?.label ?? key;
    mutation.mutate(uiToPresence(key), {
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
          active ? active.bg : "border-border bg-surface",
        )}
      >
        {active ? (
          <>
            <span className={cn("h-100 w-100 rounded-full", active.dot)} />
            <span className={cn("text-body-small font-medium", active.text)}>{active.label}</span>
          </>
        ) : presence.isError ? (
          <button
            type="button"
            onClick={() => void presence.refetch()}
            className="text-body-small font-medium text-text-danger hover:underline"
          >
            Status unavailable · Retry
          </button>
        ) : (
          <span className="text-body-small text-text-subtlest">Loading status…</span>
        )}
      </div>
      <RadioGroup.Root
        value={status ?? ""}
        onValueChange={setStatus}
        disabled={mutation.isPending || !status}
        orientation="horizontal"
        aria-label="Availability"
        className="inline-flex rounded-medium border border-border bg-surface p-025"
      >
        {options.map((o) => (
          <RadioGroup.Item
            key={o.key}
            value={o.key}
            className={cn(
              "rounded-medium px-150 py-075 text-body-small font-medium transition-colors disabled:opacity-60",
              "data-[state=checked]:bg-background-brand-bold data-[state=checked]:text-text-inverse",
              "data-[state=unchecked]:text-text-subtle data-[state=unchecked]:hover:bg-surface-sunken",
            )}
          >
            {o.label}
          </RadioGroup.Item>
        ))}
      </RadioGroup.Root>
    </div>
  );
}
