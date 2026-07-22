import { useState } from "react";
import { cn } from "@/lib/utils";

type Status = "available" | "break" | "wrap";

const options: { key: Status; label: string; dot: string; ring: string; text: string; bg: string }[] = [
  { key: "available", label: "Available", dot: "bg-success", ring: "pulse-dot", text: "text-success", bg: "bg-success-bg" },
  { key: "break", label: "On break", dot: "bg-warning", ring: "", text: "text-warning", bg: "bg-warning-bg" },
  { key: "wrap", label: "Wrap-up", dot: "bg-info", ring: "", text: "text-info", bg: "bg-brand-tint" },
];

export function AvailabilityToggle() {
  const [status, setStatus] = useState<Status>("available");
  const active = options.find((o) => o.key === status)!;

  return (
    <div className="flex items-center gap-3">
      <div className={cn("flex items-center gap-2 rounded-full px-3 py-1.5", active.bg)}>
        <span className={cn("h-2 w-2 rounded-full", active.dot, active.ring)} />
        <span className={cn("text-[12px] font-semibold", active.text)}>{active.label}</span>
      </div>
      <div className="inline-flex rounded-md border border-[var(--border-token)] bg-surface-card p-0.5 shadow-card">
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            onClick={() => setStatus(o.key)}
            className={cn(
              "rounded-[6px] px-3 py-1.5 text-[12px] font-medium transition-colors",
              status === o.key
                ? "bg-brand-primary text-white"
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
