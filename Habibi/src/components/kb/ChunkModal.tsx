import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { KbChunk } from "@/data/kb-seed";

export function ChunkModal({
  chunk,
  onClose,
}: {
  chunk: KbChunk | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!chunk} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        {chunk && (
          <>
            <DialogHeader>
              <DialogTitle className="text-base">{chunk.heading}</DialogTitle>
            </DialogHeader>
            <div className="flex items-center gap-3 text-[11px] text-text-muted">
              <span className="font-mono">chunk #{chunk.index}</span>
              <span>{chunk.tokens} tokens</span>
              <span>{chunk.hits} retrieval hits (30d)</span>
            </div>
            <div className="mt-2 max-h-[60vh] overflow-y-auto rounded-md border border-[var(--border-token)] bg-surface-app p-4 text-[13px] leading-relaxed text-text-primary">
              {chunk.text}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
