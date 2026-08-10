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

const SHIFT_TZ = "Asia/Kolkata";

/** Fixed IST shift 09:00–18:30 — live remaining clock. */
function useShiftLine() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const today = now.toLocaleDateString("en-IN", {
    timeZone: SHIFT_TZ,
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  const istClock = new Intl.DateTimeFormat("en-GB", {
    timeZone: SHIFT_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const istHour = Number(istClock.find((p) => p.type === "hour")?.value ?? 0);
  const istMinute = Number(istClock.find((p) => p.type === "minute")?.value ?? 0);
  const nowMins = istHour * 60 + istMinute;
  const startMins = SHIFT_START_H * 60 + SHIFT_START_M;
  const endMins = SHIFT_END_H * 60 + SHIFT_END_M;

  const endLabel = "6:30 PM";

  let shiftNote: string;
  if (nowMins < startMins) {
    const mins = startMins - nowMins;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    shiftNote = `Shift starts at 9:00 AM · in ${h > 0 ? `${h}h ` : ""}${m}m`;
  } else if (nowMins >= endMins) {
    shiftNote = `Shift ended at ${endLabel}`;
  } else {
    const mins = endMins - nowMins;
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
        <div className="mx-auto w-full max-w-[90rem] px-300 py-300">
          <div className="flex flex-wrap items-start justify-between gap-200">
            <div>
              <h1 className="heading-medium text-text">
                {greeting()}, {name}
              </h1>
              <p className="mt-075 text-body text-text-subtle">{shiftLine}</p>
            </div>
            <AvailabilityToggle />
          </div>

          {outsideWindowCount > 0 && (
            <div className="mt-250 flex items-start gap-150 rounded-xlarge border border-border-warning/25 bg-background-warning px-200 py-150">
              <ShieldAlert className="mt-025 h-4 w-4 shrink-0 text-text-warning" />
              <div className="min-w-0 text-body">
                <span className="font-semibold text-text-warning">
                  {outsideWindowCount} queue item{outsideWindowCount === 1 ? " is" : "s are"}{" "}
                  outside the allowed contact window.
                </span>{" "}
                <span className="text-text-subtle">
                  Respect DND rules — reschedule or wait until the customer's permitted hours.
                </span>
              </div>
              <button
                type="button"
                onClick={() => void navigate({ to: "/consent" })}
                className="ml-auto shrink-0 rounded-medium border border-border-warning/30 bg-surface px-150 py-075 text-body-small font-semibold text-text-warning hover:bg-background-warning"
              >
                Review consent
              </button>
            </div>
          )}

          <div className="mt-300">
            <StatsStrip />
          </div>

          {/* items-start: columns keep their own height. Queue uses a fixed
              row-viewport so chip switches don't resize the card. */}
          <div className="mt-300 grid items-start gap-200 lg:grid-cols-3">
            <div className="min-w-0 lg:col-span-2">
              <AssignedQueue />
            </div>
            <div className="min-w-0">
              <RightRail />
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
