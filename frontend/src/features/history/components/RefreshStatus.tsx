/**
 * "Updated 12s ago · Refresh" — the age of what a history page is showing,
 * plus a manual way to ask for more (review R2-03).
 *
 * Shared by `/aircraft`, `/sightings`, `/activity` and both detail routes,
 * which is why it lives in `features/history/` rather than inside any one of
 * them: the five pages have one refresh contract between them, and a reader
 * who learns what this line means on one page has learned it for all five.
 *
 * The age ticks on its own (`useRelativeAge`) because `dataUpdatedAt` is an
 * instant, not a counter — without that the line would itself go stale, which
 * is precisely the failure it exists to expose. It is deliberately *not* a
 * live region: a value that changes every second would make a screen reader
 * unusable (the same mistake R1-15 records on the Live Map's connection
 * chip), so the number is available on demand and announced never.
 */

import { RefreshCw } from "lucide-react";

import { useRelativeAge } from "@/features/aircraft-detail/lib/useRelativeAge";
import { cn } from "@/lib/utils";

export interface RefreshStatusProps {
  /** TanStack Query's `dataUpdatedAt`: ms since the epoch, `0` before the
   * query has ever succeeded. */
  updatedAt: number;
  /** `isFetching` — dims the line and disables the button while in flight. */
  isFetching: boolean;
  /** `refetch`, bound by the caller. */
  onRefresh: () => void;
  /** The automatic cadence in milliseconds, named in the button's title so
   * "why did this change on its own?" has an answer. `null` when this page
   * (or this page number) does not poll. */
  intervalMs?: number | null;
  className?: string;
}

function cadenceLabel(intervalMs: number): string {
  const seconds = Math.round(intervalMs / 1000);
  return seconds % 60 === 0 && seconds >= 60
    ? `${seconds / 60} min`
    : `${seconds}s`;
}

export function RefreshStatus({
  updatedAt,
  isFetching,
  onRefresh,
  intervalMs = null,
  className,
}: RefreshStatusProps) {
  const age = useRelativeAge(
    updatedAt > 0 ? new Date(updatedAt).toISOString() : null,
  );

  return (
    <p
      data-testid="refresh-status"
      className={cn(
        "flex items-center gap-2 text-xs text-muted-foreground",
        className,
      )}
    >
      <span>
        {age === null
          ? "Not loaded yet"
          : isFetching
            ? "Updating…"
            : `Updated ${age}`}
      </span>
      <button
        type="button"
        onClick={onRefresh}
        disabled={isFetching}
        title={
          intervalMs === null
            ? "Fetch the latest data now"
            : `Refreshes automatically every ${cadenceLabel(intervalMs)}`
        }
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-accent",
          "outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        <RefreshCw
          aria-hidden="true"
          className={cn("size-3", isFetching && "animate-spin")}
        />
        Refresh
      </button>
    </p>
  );
}
