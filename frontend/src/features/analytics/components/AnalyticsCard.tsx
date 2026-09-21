/**
 * The card shell every Analytics tile renders through: a title, the echoed
 * window shown subtly beneath it (`docs/API.md` §3.7 — every response
 * carries the window it actually resolved, so it never goes unshown), and a
 * loading/error/content body. Kept separate from `EChart` because two of the
 * eight tiles (rarity lists) render a table, not a chart.
 */
import type { ReactNode } from "react";

import type { AnalyticsWindow } from "@/lib/api/analytics";

import { Button } from "@/components/ui/button";
import { formatWindowLabel } from "@/features/analytics/lib/format";

export interface AnalyticsCardProps {
  title: string;
  /** `undefined` while the query is still pending — the window caption is
   * simply omitted until it arrives, rather than showing a stale one. */
  window?: AnalyticsWindow;
  isLoading: boolean;
  /** The query's error message, if any — shown in place of `children`. */
  error?: string;
  /** Refetches the query behind this card (R3-05) — omitted for a card whose
   * failure is already explained and retried by a page-level banner instead
   * of its own button (R3-08's daily-backed cards). */
  onRetry?: () => void;
  children: ReactNode;
}

export function AnalyticsCard({
  title,
  window,
  isLoading,
  error,
  onRetry,
  children,
}: AnalyticsCardProps) {
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <header>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {window !== undefined && (
          // The echoed window is the one place the page states, in the user's
          // own view, which range it is actually showing — so it is what the
          // E2E preset flow asserts changed, rather than trusting that a
          // clicked button re-queried anything.
          <p
            data-testid="analytics-card-window"
            className="text-xs text-muted-foreground"
          >
            {formatWindowLabel(window)}
          </p>
        )}
      </header>
      {isLoading ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Loading…
        </p>
      ) : error !== undefined ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <p className="text-sm text-destructive">{error}</p>
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
