import type { ReactNode } from "react";

interface ChartCardProps {
  titleId: string;
  title: string;
  isLoading?: boolean;
  /** The query's error message, if any — shown in place of `children`. Mirrors
   * `features/analytics/components/AnalyticsCard.tsx`'s loading/error shape,
   * the pattern roadmap slice 032 established for every chart card. */
  error?: string;
  children: ReactNode;
}

/** Shared card chrome for every Receiver page chart (SPEC §62): a titled,
 * bordered panel matching the app's existing `bg-card`/`border-border`
 * tokens (see `features/aircraft-detail/AircraftDetailPanel.tsx`). */
export function ChartCard({
  titleId,
  title,
  isLoading,
  error,
  children,
}: ChartCardProps) {
  return (
    <section
      aria-labelledby={titleId}
      className="rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id={titleId} className="mb-2 text-sm font-medium">
        {title}
      </h3>
      {isLoading === true ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Loading…
        </p>
      ) : error !== undefined ? (
        <p className="py-8 text-center text-sm text-destructive">{error}</p>
      ) : (
        children
      )}
    </section>
  );
}
