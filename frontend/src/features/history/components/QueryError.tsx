/**
 * The two shapes a failed history-page request takes (review R2-04, R2-17).
 *
 * The distinction is *what the reader still has*. If a page has never
 * loaded, there is nothing to keep and the failure is the page —
 * {@link QueryErrorState}. If it has loaded before, the rows on screen are
 * still the best answer anyone has, and unmounting them (with their sort
 * headers and their pagination, as the review found) leaves no control
 * capable of asking again: that case is a banner *above* the data it failed
 * to replace — {@link QueryErrorBanner}.
 *
 * Both carry `role="alert"`, so the failure is announced rather than merely
 * turning red, and both pair the colour with a warning glyph so red is not
 * the only channel.
 */

import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface QueryErrorProps {
  /** What went wrong, in the caller's words ("Could not load the aircraft
   * list") — the underlying message is appended by the caller if it is worth
   * showing. */
  message: string;
  /** `query.refetch`, bound by the caller. */
  onRetry: () => void;
  /** Disables the retry control while a retry is already in flight. */
  isRetrying?: boolean;
  className?: string;
}

/** A failure *behind* data that is still on screen. */
export function QueryErrorBanner({
  message,
  onRetry,
  isRetrying = false,
  className,
}: QueryErrorProps) {
  return (
    <div
      role="alert"
      data-testid="query-error-banner"
      className={cn(
        "mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm",
        className,
      )}
    >
      <AlertTriangle
        aria-hidden="true"
        className="size-4 shrink-0 text-destructive"
      />
      <p className="min-w-0 flex-1 text-destructive">
        {message} Showing the last data that loaded.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={isRetrying}
        onClick={onRetry}
      >
        {isRetrying ? "Retrying…" : "Try again"}
      </Button>
    </div>
  );
}

/** A failure with nothing behind it: the page has never loaded. */
export function QueryErrorState({
  message,
  onRetry,
  isRetrying = false,
  className,
}: QueryErrorProps) {
  return (
    <div
      role="alert"
      data-testid="query-error-state"
      className={cn(
        "flex flex-col items-start gap-3 rounded-lg border border-border bg-card px-4 py-6",
        className,
      )}
    >
      <p className="flex items-start gap-2 text-sm text-destructive">
        <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>{message}</span>
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={isRetrying}
        onClick={onRetry}
      >
        {isRetrying ? "Retrying…" : "Try again"}
      </Button>
    </div>
  );
}
