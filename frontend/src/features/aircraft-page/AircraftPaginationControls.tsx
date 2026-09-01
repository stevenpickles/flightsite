/**
 * Prev/Next paging for the Aircraft table, plus a page/count summary.
 * `total` is `null` when the backend omits it (§2.4 allows that on
 * `/aircraft`, even though today's implementation always returns an exact
 * count — see `flightsite.api.history`) — in that case "Next" stays
 * enabled whenever a full page came back, since there is no total to
 * compare against.
 */

import { Button } from "@/components/ui/button";

export interface AircraftPaginationControlsProps {
  page: number;
  pageSize: number;
  rowCount: number;
  total: number | null;
  onPageChange: (page: number) => void;
}

export function AircraftPaginationControls({
  page,
  pageSize,
  rowCount,
  total,
  onPageChange,
}: AircraftPaginationControlsProps) {
  const totalPages =
    total === null ? null : Math.max(1, Math.ceil(total / pageSize));
  const canGoBack = page > 1;
  const canGoForward =
    totalPages === null ? rowCount === pageSize : page < totalPages;

  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm text-muted-foreground">
      <p>
        {total === null
          ? `Page ${page}`
          : `Page ${page} of ${totalPages} · ${total.toLocaleString()} aircraft`}
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canGoBack}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canGoForward}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
