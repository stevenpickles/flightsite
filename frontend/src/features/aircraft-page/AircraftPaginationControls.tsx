/**
 * Prev/Next paging for a paginated table, plus a page/count summary.
 * `total` is `null` when the backend omits it (§2.4 allows that on
 * `/aircraft`, even though today's implementation always returns an exact
 * count — see `flightsite.api.history`) — in that case "Next" stays
 * enabled whenever a full page came back, since there is no total to
 * compare against.
 *
 * Shared by `/aircraft`, `/sightings` and `/activity`, so what the count
 * counts is a prop rather than the hardcoded "aircraft" it used to be
 * (issue #112).
 */

import { Button } from "@/components/ui/button";

/** What the `total` counts, in both forms.
 *
 * Two fields rather than one because English does not agree with itself here:
 * "aircraft" is invariant, so both forms are the same word and the original
 * hardcoded label read correctly at any count by luck. "sighting"/"sightings"
 * is not, so a shared footer cannot get away with one string. */
export interface PaginationNoun {
  singular: string;
  plural: string;
}

export interface AircraftPaginationControlsProps {
  page: number;
  pageSize: number;
  rowCount: number;
  total: number | null;
  /** Required, not defaulted to "aircraft": a default would leave a new call
   * site silently mislabelled, which is the bug this prop exists to fix. */
  noun: PaginationNoun;
  onPageChange: (page: number) => void;
}

export function AircraftPaginationControls({
  page,
  pageSize,
  rowCount,
  total,
  noun,
  onPageChange,
}: AircraftPaginationControlsProps) {
  const totalPages =
    total === null ? null : Math.max(1, Math.ceil(total / pageSize));
  const canGoBack = page > 1;
  const canGoForward =
    totalPages === null ? rowCount === pageSize : page < totalPages;
  // "Page 999 of 2" is a sentence that contradicts itself, and the footer
  // used to print it for any out-of-range `?page=` (review R2-09).
  const pastTheEnd = totalPages !== null && page > totalPages;
  // Back from past the end goes to the last page that exists, not to page
  // 998 — which is also empty, and was the only recovery on offer.
  const previousPage =
    pastTheEnd && totalPages !== null ? totalPages : page - 1;

  const counted =
    total === null
      ? null
      : `${total.toLocaleString()} ${total === 1 ? noun.singular : noun.plural}`;

  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm text-muted-foreground">
      <p>
        {counted === null
          ? `Page ${page}`
          : pastTheEnd
            ? `Page ${page} is past the end · ${counted}`
            : `Page ${page} of ${totalPages} · ${counted}`}
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canGoBack}
          onClick={() => onPageChange(previousPage)}
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
