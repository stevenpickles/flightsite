import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface ChartCardProps {
  titleId: string;
  title: string;
  isLoading?: boolean;
  /** The query's error message, if any — shown in place of `children`. Mirrors
   * `features/analytics/components/AnalyticsCard.tsx`'s loading/error shape,
   * the pattern roadmap slice 032 established for every chart card. */
  error?: string;
  /** Refetches the query behind this card (R3-05) — a failed chart otherwise
   * never recovers short of a preset/window change or a full reload. */
  onRetry?: () => void;
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
  onRetry,
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
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          {onRetry !== undefined && (
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          )}
        </div>
      ) : (
        children
      )}
    </section>
  );
}
