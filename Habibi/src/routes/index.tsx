import { createFileRoute } from "@tanstack/react-router";
import { ShieldAlert } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { AvailabilityToggle } from "@/components/workspace/AvailabilityToggle";
import { StatsStrip } from "@/components/workspace/StatsStrip";
import { AssignedQueue } from "@/components/workspace/AssignedQueue";
import { RightRail } from "@/components/workspace/RightRail";
import { outsideWindowCount } from "@/data/workspace-seed";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "My Workspace — Collections Agent" },
      {
        name: "description",
        content:
          "Agent shift home base — assigned queue, callbacks, SLA countdowns, and today's stats for the Collections AI workspace.",
      },
    ],
  }),
  component: WorkspacePage,
});

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function WorkspacePage() {
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <AppShell>
      {/* AppShell main is overflow-hidden; this page must own its scroll. */}
      <div className="h-full min-h-0 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1440px] px-6 py-6">
          {/* Greeting + availability */}
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-[24px] font-bold text-brand-navy">{greeting()}, Priya</h1>
              <p className="mt-1 text-[13px] text-text-secondary">
                {today} · Shift ends at 6:30 PM · 3h 12m remaining
              </p>
            </div>
            <AvailabilityToggle />
          </div>

          {/* Consent nudge */}
          {outsideWindowCount > 0 && (
            <div className="mt-5 flex items-start gap-3 rounded-[10px] border border-[var(--border-token)] bg-warning-bg px-4 py-3">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <div className="text-[13px]">
                <span className="font-semibold text-warning">
                  {outsideWindowCount} queue item is outside the allowed contact window.
                </span>{" "}
                <span className="text-text-secondary">
                  Respect DND rules — reschedule or wait until the customer's permitted hours.
                </span>
              </div>
              <button
                type="button"
                className="ml-auto shrink-0 rounded-md border border-warning/30 bg-white px-2.5 py-1 text-[12px] font-medium text-warning hover:bg-warning-bg"
              >
                Review consent
              </button>
            </div>
          )}

          {/* Stats */}
          <div className="mt-6">
            <StatsStrip />
          </div>

          {/* Main grid */}
          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <AssignedQueue />
            </div>
            <div>
              <RightRail />
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
