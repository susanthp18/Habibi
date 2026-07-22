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
import type { ChannelConsent, AllowedWindow, ConsentRecord, ConsentChannel, OptOutSource } from "@/data/consent-seed";

const SOURCES: OptOutSource[] = ["Agent", "IVR", "Web", "Regulator", "Bulk Import", "WhatsApp Reply"];

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
  onSave: (id: string, patch: { channels: ChannelConsent[]; allowedWindow: AllowedWindow }, note: string) => void;
  onRenew: (id: string) => void;
  onCaptureOptOut: (id: string, evt: { channel: ConsentChannel | "all"; source: OptOutSource; note: string }) => void;
  onToggleDnd: (id: string, on: boolean) => void;
}) {
  const [channels, setChannels] = useState<ChannelConsent[]>([]);
  const [window, setWindow] = useState<AllowedWindow>({ days: [1, 2, 3, 4, 5], startHour: 10, endHour: 19 });
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
      <SheetContent side="right" className="w-full max-w-[560px] overflow-y-auto p-0 sm:max-w-[560px]">
        <SheetHeader className="sticky top-0 z-10 border-b border-[var(--border-token)] bg-surface-card p-4">
          <div className="flex items-center gap-2">
            <ContactablePill record={record} />
            <span className="ml-auto rounded-full bg-surface-sunken px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary">
              {record.segment}
            </span>
          </div>
          <SheetTitle className="text-left text-[16px] font-semibold text-brand-navy">
            {record.customerName}
          </SheetTitle>
          <div className="grid grid-cols-2 gap-1 text-[11px] text-text-secondary">
            <div><span className="text-text-muted">Account:</span> <span className="font-mono">{record.accountId}</span></div>
            <div><span className="text-text-muted">Phone:</span> {record.phone}</div>
            <div className="col-span-2"><span className="text-text-muted">Email:</span> {record.email}</div>
          </div>
        </SheetHeader>

        <div className="space-y-4 p-4">
          <section>
            <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Channel matrix
              <button
                onClick={() => onToggleDnd(record.id, !record.onDndRegistry)}
                className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  record.onDndRegistry
                    ? "bg-[color:var(--danger-bg)] text-[color:var(--danger)]"
                    : "bg-surface-sunken text-text-secondary hover:bg-brand-tint hover:text-brand-primary"
                }`}
              >
                <ShieldOff className="h-3 w-3" /> DND registry {record.onDndRegistry ? "· ON" : "· off"}
              </button>
            </div>
            <ChannelMatrix channels={channels} onChange={setChannels} />
          </section>

          <section>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Allowed contact window</div>
            <AllowedHoursEditor window={window} timezone={record.timezone} onChange={setWindow} />
          </section>

          <section>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Frequency caps</div>
            <FrequencyCapsEditor channels={channels} onChange={setChannels} />
          </section>

          <section className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">Consent expiry</div>
                <div className="text-[13px] text-brand-navy">{new Date(record.consentExpiresAt).toLocaleDateString()}</div>
              </div>
              <Button size="sm" variant="outline" className="h-8" onClick={() => onRenew(record.id)}>
                <RefreshCw className="mr-1 h-3.5 w-3.5" /> Renew consent
              </Button>
            </div>
          </section>

          <section>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Capture opt-out</div>
            <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3 space-y-2">
              <div className="flex flex-wrap gap-2">
                <select
                  value={optChannel}
                  onChange={(e) => setOptChannel(e.target.value as ConsentChannel | "all")}
                  className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
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
                  className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                >
                  {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <Textarea
                value={optNote}
                onChange={(e) => setOptNote(e.target.value)}
                placeholder="How was the opt-out captured? (verbatim if possible)"
                className="min-h-[60px] text-[12px]"
              />
              <div className="flex justify-end">
                <Button size="sm" variant="outline" className="h-8" disabled={!optNote.trim()} onClick={captureOptOut}>
                  <Ban className="mr-1 h-3.5 w-3.5" /> Log opt-out
                </Button>
              </div>
            </div>
          </section>

          <section>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Opt-out log</div>
            <OptOutLog events={record.optOutLog} />
          </section>

          <section>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Audit trail</div>
            <ul className="space-y-1 text-[12px]">
              {record.audit.slice().reverse().map((a) => (
                <li key={a.id} className="rounded-md border border-[var(--border-token)] bg-surface-card p-2">
                  <div className="text-[10px] text-text-muted">{new Date(a.at).toLocaleString()} · {a.actor}</div>
                  <div>{a.action}</div>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <div className="sticky bottom-0 z-10 flex items-center gap-2 border-t border-[var(--border-token)] bg-surface-card px-4 py-3">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Change note (added to audit trail)…"
            className="min-h-[36px] flex-1 text-[12px]"
            rows={1}
          />
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" className="bg-brand-primary hover:bg-brand-primary-hover" onClick={save}>Save changes</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
