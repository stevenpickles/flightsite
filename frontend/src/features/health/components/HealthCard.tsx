import type { ReactNode } from "react";

interface HealthCardProps {
  titleId: string;
  title: string;
  /** Rendered at the right of the header — usually a `<StatusPill />`. */
  status?: ReactNode;
  description?: string;
  children: ReactNode;
}

/**
 * Shared card chrome for the health area (SPEC §67), matching the
 * `bg-card`/`border-border` panel `features/receiver/components/ChartCard.tsx`
 * established rather than introducing a second card look.
 */
export function HealthCard({
  titleId,
  title,
  status,
  description,
  children,
}: HealthCardProps) {
  return (
    <section
      aria-labelledby={titleId}
      className="rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 id={titleId} className="text-sm font-medium">
            {title}
          </h2>
          {description !== undefined && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {status}
      </div>
      {children}
    </section>
  );
}

interface StatTileProps {
  label: string;
  value: ReactNode;
  secondary?: ReactNode;
}

/** One labelled figure. Mirrors the Receiver scorecard's tile so the two
 * pages read as the same app. */
export function StatTile({ label, value, secondary }: StatTileProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-card-foreground">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {secondary !== undefined && (
        <p className="mt-0.5 text-xs text-muted-foreground">{secondary}</p>
      )}
    </div>
  );
}

interface DetailRowProps {
  label: string;
  value: ReactNode;
}

/** A label/value pair inside a card. */
export function DetailRow({ label, value }: DetailRowProps) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium tabular-nums">{value}</span>
    </div>
  );
}
