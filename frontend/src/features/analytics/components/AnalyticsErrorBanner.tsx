/**
 * A single page-level failure notice for the Analytics page (R3-08): before
 * this, a shared query backing several cards (`/analytics/daily` backs
 * four) printed the identical error string once per card, and a total
 * outage printed "Failed to fetch" nine times with no statement that the
 * whole page — not nine unrelated things — was the problem. One of these
 * replaces all of that with one message and one Retry.
 */
import { Button } from "@/components/ui/button";

export interface AnalyticsErrorBannerProps {
  message: string;
  /** The backend's raw error text, if any — attached as a hover/inspect
   * `title` rather than a second visible line, so it never reads as a more
   * alarming message than the human one above it (R3-08). */
  detail?: string;
  onRetry: () => void;
}

export function AnalyticsErrorBanner({
  message,
  detail,
  onRetry,
}: AnalyticsErrorBannerProps) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3"
    >
      <p className="text-sm font-medium text-destructive" title={detail}>
        {message}
      </p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
