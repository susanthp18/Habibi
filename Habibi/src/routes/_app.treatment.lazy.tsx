import { createLazyFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const Route = createLazyFileRoute("/_app/treatment")({
  component: TreatmentPage,
});

import { CasesTab } from "@/components/treatment/CasesTab";
import { DecisionsTab } from "@/components/treatment/DecisionsTab";
import { HoldsTab } from "@/components/treatment/HoldsTab";
import { InsightsTab } from "@/components/treatment/InsightsTab";
import { ModelsTab } from "@/components/treatment/ModelsTab";
import { OpsTab } from "@/components/treatment/OpsTab";
import { ResultsTab } from "@/components/treatment/ResultsTab";
import { StrategyTab } from "@/components/treatment/StrategyTab";
import { TodayTab } from "@/components/treatment/TodayTab";

const WINDOWS = [1, 7, 14, 28, 90] as const;
const TABS = [
  "today",
  "decisions",
  "results",
  "strategy",
  "cases",
  "holds",
  "mandates",
  "field",
  "legal",
  "advanced",
] as const;

export function TreatmentPage() {
  const [days, setDays] = useState<number>(7);
  const search = useSearch({ strict: false });
  const tab = TABS.find((t) => t === search.tab) ?? "today";
  const navigate = useNavigate();

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-center justify-between gap-200 border-b border-border bg-surface px-300 py-150">
          <div className="min-w-0">
            <h1 className="text-body font-semibold text-text">Decision intelligence</h1>
            <p className="text-body-small text-text-subtle">
              What the engine decided for each borrower and why, what happened next, whether it
              is working, and what it has learned.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-100">
            <Label htmlFor="treatment-window" className="text-body-small text-text-subtle">
              Window
            </Label>
            <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
              <SelectTrigger id="treatment-window" className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WINDOWS.map((w) => (
                  <SelectItem key={w} value={String(w)}>
                    {w === 1 ? "Today" : `Last ${w} days`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <Tabs
          value={tab}
          onValueChange={(next) => {
            const nextTab = TABS.find((t) => t === next);
            if (!nextTab) return;
            void navigate({
              to: "/treatment",
              search: { tab: nextTab, customerId: search.customerId },
            });
          }}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <TabsList className="h-10 w-full shrink-0 justify-start overflow-x-auto px-300">
            <TabsTrigger value="today">Today</TabsTrigger>
            <TabsTrigger value="decisions">Decisions</TabsTrigger>
            <TabsTrigger value="results">Is it working?</TabsTrigger>
            <TabsTrigger value="strategy">Strategy</TabsTrigger>
            <TabsTrigger value="cases">Cases</TabsTrigger>
            <TabsTrigger value="holds">Holds</TabsTrigger>
            <TabsTrigger value="mandates">Mandates</TabsTrigger>
            <TabsTrigger value="field">Field</TabsTrigger>
            <TabsTrigger value="legal">Legal</TabsTrigger>
            <TabsTrigger value="advanced">Advanced</TabsTrigger>
          </TabsList>

          <TabsContent value="today" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <TodayTab days={days} />
          </TabsContent>
          <TabsContent value="decisions" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <DecisionsTab customerId={search.customerId} />
          </TabsContent>
          <TabsContent value="results" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <ResultsTab days={days} />
          </TabsContent>
          <TabsContent value="strategy" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <StrategyTab />
          </TabsContent>
          <TabsContent value="advanced" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <div className="flex flex-col gap-300">
              <p className="text-body-small text-text-subtle">
                For data scientists: the full scoreboard, model calibration and drift, and the
                champion/challenger ledger.
              </p>
              <InsightsTab days={days} />
              <ModelsTab days={days} />
            </div>
          </TabsContent>
          <TabsContent value="cases" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <CasesTab customerId={search.customerId} />
          </TabsContent>
          <TabsContent
            value="mandates"
            className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200"
          >
            <OpsTab kind="mandates" customerId={search.customerId} />
          </TabsContent>
          <TabsContent value="field" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <OpsTab kind="field" customerId={search.customerId} />
          </TabsContent>
          <TabsContent value="legal" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <OpsTab kind="legal" customerId={search.customerId} />
          </TabsContent>
          <TabsContent value="holds" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <HoldsTab />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
