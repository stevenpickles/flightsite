/**
 * One stat tile in the Today panel's grid — the same visual shape as
 * `features/receiver/components/ReceiverScorecard.tsx`'s `StatTile`,
 * duplicated rather than imported (that file is Receiver-page-local, and
 * this feature stays a self-contained read of its own few small files, the
 * convention `features/receiver/lib/format.ts`'s doc comment states).
 */
import type { ReactNode } from "react";

export interface StatTileProps {
  label: string;
  value: ReactNode;
  secondary?: ReactNode;
}

export function StatTile({ label, value, secondary }: StatTileProps) {
  return (
    <div className="rounded-md border border-border bg-card p-2.5 text-card-foreground">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
      {secondary !== undefined && (
        <p className="mt-0.5 text-[11px] text-muted-foreground">{secondary}</p>
      )}
    </div>
  );
}
