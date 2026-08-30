import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { KbChunk } from "@/data/kb-seed";

export function ChunkModal({ chunk, onClose }: { chunk: KbChunk | null; onClose: () => void }) {
  return (
    <Dialog open={!!chunk} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        {chunk && (
          <>
            <DialogHeader>
              <DialogTitle className="text-base">{chunk.heading}</DialogTitle>
            </DialogHeader>
            <div className="flex items-center gap-150 text-body-small text-text-subtlest">
              <span className="font-mono">chunk #{chunk.index}</span>
              <span>{chunk.tokens} tokens</span>
              <span>{chunk.hits} retrieval hits (30d)</span>
            </div>
            <div className="mt-100 max-h-[60vh] overflow-y-auto rounded-medium border border-border bg-surface p-200 text-body leading-relaxed text-text">
              {chunk.text}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
