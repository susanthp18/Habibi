import { createLazyFileRoute } from "@tanstack/react-router";
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

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------
import { InsightsTab } from "@/components/treatment/InsightsTab";
import { ModelsTab } from "@/components/treatment/ModelsTab";
import { CasesTab } from "@/components/treatment/CasesTab";
import { HoldsTab } from "@/components/treatment/HoldsTab";

const WINDOWS = [7, 14, 28, 90] as const;

export function TreatmentPage() {
  const [days, setDays] = useState<number>(14);
  const [tab, setTab] = useState("insights");

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-center justify-between gap-200 border-b border-border bg-surface px-300 py-150">
          <div className="min-w-0">
            <h1 className="text-body font-semibold text-text">Decision intelligence</h1>
            <p className="text-body-small text-text-subtle">
              What the treatment engine decided, why it was suppressed, and whether the models
              behind it are still calibrated.
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
                    Last {w} days
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <Tabs
          value={tab}
          onValueChange={setTab}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <TabsList className="h-10 w-full shrink-0 justify-start px-300">
            <TabsTrigger value="insights">Insights</TabsTrigger>
            <TabsTrigger value="models">Model health</TabsTrigger>
            <TabsTrigger value="cases">Cases</TabsTrigger>
            <TabsTrigger value="holds">Holds</TabsTrigger>
          </TabsList>

          <TabsContent
            value="insights"
            className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200"
          >
            <InsightsTab days={days} />
          </TabsContent>
          <TabsContent value="models" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <ModelsTab days={days} />
          </TabsContent>
          <TabsContent value="cases" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <CasesTab />
          </TabsContent>
          <TabsContent value="holds" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <HoldsTab />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Insights — GET /treatment/insights + GET /treatment/metrics
// ---------------------------------------------------------------------------
