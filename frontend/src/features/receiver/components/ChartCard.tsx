import type { ReactNode } from "react";

interface ChartCardProps {
  titleId: string;
  title: string;
  children: ReactNode;
}

/** Shared card chrome for every Receiver page chart (SPEC §62): a titled,
 * bordered panel matching the app's existing `bg-card`/`border-border`
 * tokens (see `features/aircraft-detail/AircraftDetailPanel.tsx`). */
export function ChartCard({ titleId, title, children }: ChartCardProps) {
  return (
    <section
      aria-labelledby={titleId}
      className="rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id={titleId} className="mb-2 text-sm font-medium">
        {title}
      </h3>
      {children}
    </section>
  );
}
