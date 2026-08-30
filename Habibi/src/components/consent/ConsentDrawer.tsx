import { useEffect, useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { RefreshCw, ShieldOff, Ban } from "lucide-react";
import { ChannelMatrix } from "./ChannelMatrix";
import { AllowedHoursEditor } from "./AllowedHoursEditor";
import { FrequencyCapsEditor } from "./FrequencyCapsEditor";
import { OptOutLog } from "./OptOutLog";
import { ContactablePill } from "./ContactablePill";
import type {
  ChannelConsent,
  AllowedWindow,
  ConsentRecord,
  ConsentChannel,
  OptOutSource,
} from "@/data/consent-seed";
import { Lozenge } from "@/components/ui/lozenge";

const SOURCES: OptOutSource[] = [
  "Agent",
  "IVR",
  "Web",
  "Regulator",
  "Bulk Import",
  "WhatsApp Reply",
];

export function ConsentDrawer({
  record,
  onClose,
  onSave,
  onRenew,
  onCaptureOptOut,
  onToggleDnd,
}: {
  record: ConsentRecord | null;
  onClose: () => void;
  onSave: (
    id: string,
    patch: { channels: ChannelConsent[]; allowedWindow: AllowedWindow },
    note: string,
  ) => void;
  onRenew: (id: string) => void;
  onCaptureOptOut: (
    id: string,
    evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string },
  ) => void;
  onToggleDnd: (id: string, on: boolean) => void;
}) {
  const [channels, setChannels] = useState<ChannelConsent[]>([]);
  const [window, setWindow] = useState<AllowedWindow>({
    days: [1, 2, 3, 4, 5],
    startHour: 10,
    endHour: 19,
  });
  const [note, setNote] = useState("");
  const [optChannel, setOptChannel] = useState<ConsentChannel | "all">("call");
  const [optSource, setOptSource] = useState<OptOutSource>("Agent");
  const [optNote, setOptNote] = useState("");

  useEffect(() => {
    if (record) {
      setChannels(record.channels);
      setWindow(record.allowedWindow);
      setNote("");
      setOptNote("");
    }
  }, [record?.id]);

  if (!record) return null;

  const save = () => {
    onSave(record.id, { channels, allowedWindow: window }, note || "Consent preferences updated.");
    setNote("");
  };
  const captureOptOut = () => {
    if (!optNote.trim()) return;
    onCaptureOptOut(record.id, { channel: optChannel, source: optSource, note: optNote.trim() });
    setOptNote("");
  };

  return (
    <Sheet open={!!record} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="w-full max-w-[37.5rem] overflow-y-auto p-0 sm:max-w-[37.5rem]"
      >
        <SheetHeader className="sticky top-0 z-10 border-b border-border bg-surface p-200">
          <div className="flex items-center gap-100">
            <ContactablePill record={record} />
            <Lozenge tone="neutral" className="ml-auto">
              {record.segment}
            </Lozenge>
          </div>
          <SheetTitle className="text-left heading-small font-semibold text-text">
            {record.customerName}
          </SheetTitle>
          <div className="grid grid-cols-2 gap-050 text-body-small text-text-subtle">
            <div>
              <span className="text-text-subtlest">Account:</span>{" "}
              <span className="font-mono">{record.accountId}</span>
            </div>
            <div>
              <span className="text-text-subtlest">Phone:</span> {record.phone}
            </div>
            <div className="col-span-2">
              <span className="text-text-subtlest">Email:</span> {record.email}
            </div>
          </div>
        </SheetHeader>

        <div className="space-y-200 p-200">
          <section>
            <div className="mb-050 flex items-center gap-100 text-body-small font-semibold text-text-subtlest">
              Channel matrix
              <button
                onClick={() => onToggleDnd(record.id, !record.onDndRegistry)}
                className={`ml-auto inline-flex items-center gap-050 rounded-full px-100 py-025 text-body-small font-semibold ${
                  record.onDndRegistry
                    ? "bg-[color:var(--danger-bg)] text-text-danger"
                    : "bg-surface-sunken text-text-subtle hover:bg-background-brand-subtlest hover:text-text-brand"
                }`}
              >
                <ShieldOff className="h-3 w-3" /> DND registry{" "}
                {record.onDndRegistry ? "· ON" : "· off"}
              </button>
            </div>
            <ChannelMatrix channels={channels} onChange={setChannels} />
          </section>

          <section>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Allowed contact window
            </div>
            <AllowedHoursEditor window={window} timezone={record.timezone} onChange={setWindow} />
          </section>

          <section>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Frequency caps
            </div>
            <FrequencyCapsEditor channels={channels} onChange={setChannels} />
            <div className="mt-075 text-body-small text-text-subtle">
              Today: {record.outreachToday ?? 0}/{record.dailyCap ?? 3} outreach
              {record.lastDecisionReason ? ` · last block: ${record.lastDecisionReason}` : ""}
            </div>
          </section>

          <section className="rounded-medium border border-border bg-surface p-150">
            <div className="mb-100 flex items-center justify-between">
              <div>
                <div className="text-body-small font-semibold text-text-subtlest">
                  Consent expiry
                </div>
                <div className="text-body text-text">
                  {new Date(record.consentExpiresAt).toLocaleDateString()}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="h-400"
                onClick={() => onRenew(record.id)}
              >
                <RefreshCw className="mr-050 h-3.5 w-3.5" /> Renew consent
              </Button>
            </div>
          </section>

          <section>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Capture opt-out
            </div>
            <div className="rounded-medium border border-border bg-surface p-150 space-y-100">
              <div className="flex flex-wrap gap-100">
                <select
                  value={optChannel}
                  onChange={(e) => setOptChannel(e.target.value as ConsentChannel | "all")}
                  className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
                >
                  <option value="all">All channels</option>
                  <option value="call">Call</option>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="sms">SMS</option>
                  <option value="email">Email</option>
                </select>
                <select
                  value={optSource}
                  onChange={(e) => setOptSource(e.target.value as OptOutSource)}
                  className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
                >
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <Textarea
                value={optNote}
                onChange={(e) => setOptNote(e.target.value)}
                placeholder="How was the opt-out captured? (verbatim if possible)"
                className="min-h-[3.75rem] text-body-small"
              />
              <div className="flex justify-end">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-400"
                  disabled={!optNote.trim()}
                  onClick={captureOptOut}
                >
                  <Ban className="mr-050 h-3.5 w-3.5" /> Log opt-out
                </Button>
              </div>
            </div>
          </section>

          <section>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Opt-out log
            </div>
            <OptOutLog events={record.optOutLog} />
          </section>

          <section>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Audit trail
            </div>
            <ul className="space-y-050 text-body-small">
              {record.audit
                .slice()
                .reverse()
                .map((a) => (
                  <li key={a.id} className="rounded-medium border border-border bg-surface p-100">
                    <div className="text-body-small text-text-subtlest">
                      {new Date(a.at).toLocaleString()} · {a.actor}
                    </div>
                    <div>{a.action}</div>
                  </li>
                ))}
            </ul>
          </section>
        </div>

        <div className="sticky bottom-0 z-10 flex items-center gap-100 border-t border-border bg-surface px-200 py-150">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Change note (added to audit trail)…"
            className="min-h-[2.25rem] flex-1 text-body-small"
            rows={1}
          />
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            className="bg-background-brand-bold hover:bg-background-brand-bold-hovered"
            onClick={save}
          >
            Save changes
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
