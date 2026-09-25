/**
 * What a history page says when the page it was asked for holds no rows
 * (review R2-09, R2-17).
 *
 * Two different facts wearing one appearance before this. All three list
 * pages guarded their empty copy on `state.page === 1`, so `?page=999`
 * rendered a header row, no body rows, a footer reading "Page 999 of 2" and
 * no explanation — reachable in normal use from a bookmark after history is
 * pruned, or from a shared link. An empty *first* page means "nothing
 * matches"; an empty *later* page means "you are past the end", which is a
 * different sentence and needs a way back.
 *
 * `role="status"` so the change is announced: the review found no live
 * region of any kind inside `main` on any of the five routes.
 */

import { Button } from "@/components/ui/button";

export interface EmptyResultProps {
  /** What an empty page 1 means — "No sightings match these filters." */
  message: string;
  /** The page actually being shown. */
  page: number;
  onBackToFirstPage: () => void;
}

export function EmptyResult({
  message,
  page,
  onBackToFirstPage,
}: EmptyResultProps) {
  if (page <= 1) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {message}
      </p>
    );
  }

  return (
    <div
      role="status"
      data-testid="past-the-end"
      className="flex flex-col items-start gap-3 rounded-lg border border-border bg-card px-4 py-6"
    >
      <p className="text-sm text-muted-foreground">
        There is nothing on page {page} — this list has fewer pages than that.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onBackToFirstPage}
      >
        Back to page 1
      </Button>
    </div>
  );
}
