import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { AppShell } from "@/components/shell/AppShell";
import { AvailabilityToggle } from "@/components/workspace/AvailabilityToggle";
import { StatsStrip } from "@/components/workspace/StatsStrip";
import { AssignedQueue } from "@/components/workspace/AssignedQueue";
import { RightRail } from "@/components/workspace/RightRail";
import { useMe } from "@/api/me";
import { useWorkspaceSummary } from "@/api/workspace";
import { BRAND } from "@/lib/brand";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: `My Workspace — ${BRAND.titleSuffix}` },
      {
        name: "description",
        content:
          "Agent shift home base — assigned queue, callbacks, SLA countdowns, and today's stats for the BigBound AI workspace.",
      },
    ],
  }),
  component: WorkspacePage,
});

const SHIFT_START_H = 9;
const SHIFT_START_M = 0;
const SHIFT_END_H = 18;
const SHIFT_END_M = 30;

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function firstName(full: string | undefined | null): string {
  if (!full) return "";
  return full.trim().split(/\s+/)[0] ?? "";
}

/** Fixed IST shift 09:00–18:30 — live remaining clock. */
function useShiftLine() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const today = now.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  const start = new Date(now);
  start.setHours(SHIFT_START_H, SHIFT_START_M, 0, 0);
  const end = new Date(now);
  end.setHours(SHIFT_END_H, SHIFT_END_M, 0, 0);

  const endLabel = end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

  let shiftNote: string;
  if (now < start) {
    const mins = Math.max(0, Math.round((start.getTime() - now.getTime()) / 60_000));
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    shiftNote = `Shift starts at 9:00 AM · in ${h > 0 ? `${h}h ` : ""}${m}m`;
  } else if (now >= end) {
    shiftNote = `Shift ended at ${endLabel}`;
  } else {
    const mins = Math.max(0, Math.round((end.getTime() - now.getTime()) / 60_000));
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    shiftNote = `Shift ends at ${endLabel} · ${h > 0 ? `${h}h ` : ""}${m}m remaining`;
  }

  return `${today} · ${shiftNote}`;
}

function WorkspacePage() {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data: summary } = useWorkspaceSummary("me");
  const name = firstName(me?.name) || "there";
  const outsideWindowCount = summary?.outsideWindowCount ?? 0;
  const shiftLine = useShiftLine();

  return (
    <AppShell>
      <div className="h-full min-h-0 overflow-y-auto bg-[linear-gradient(180deg,rgba(231,240,254,0.35)_0%,transparent_180px)]">
        <div className="mx-auto w-full max-w-[1440px] px-6 py-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight text-brand-navy">
                {greeting()}, {name}
              </h1>
              <p className="mt-1.5 text-[13px] text-text-secondary">{shiftLine}</p>
            </div>
            <AvailabilityToggle />
          </div>

          {outsideWindowCount > 0 && (
            <div className="mt-5 flex items-start gap-3 rounded-[12px] border border-warning/25 bg-warning-bg px-4 py-3 shadow-sm">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <div className="min-w-0 text-[13px]">
                <span className="font-semibold text-warning">
                  {outsideWindowCount} queue item{outsideWindowCount === 1 ? " is" : "s are"} outside
                  the allowed contact window.
                </span>{" "}
                <span className="text-text-secondary">
                  Respect DND rules — reschedule or wait until the customer's permitted hours.
                </span>
              </div>
              <button
                type="button"
                onClick={() => void navigate({ to: "/consent" })}
                className="ml-auto shrink-0 rounded-md border border-warning/30 bg-white px-2.5 py-1.5 text-[12px] font-semibold text-warning shadow-sm hover:bg-warning-bg"
              >
                Review consent
              </button>
            </div>
          )}

          <div className="mt-6">
            <StatsStrip />
          </div>

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
