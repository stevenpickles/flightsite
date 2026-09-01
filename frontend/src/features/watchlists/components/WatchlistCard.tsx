import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { EntryForm } from "@/features/watchlists/components/EntryForm";
import { entryKindMeta } from "@/features/watchlists/lib/vocabulary";
import {
  validateWatchlistDescription,
  validateWatchlistName,
} from "@/features/watchlists/lib/validation";
import type { ApiError } from "@/lib/api/client";
import {
  useAddWatchlistEntryMutation,
  useDeleteWatchlistMutation,
  useRemoveWatchlistEntryMutation,
  useUpdateWatchlistMutation,
  useWatchlistEntriesQuery,
  type Watchlist,
} from "@/lib/api/watchlists";

function errorMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

export interface WatchlistCardProps {
  watchlist: Watchlist;
  liveMatchCount: number;
}

/**
 * One watchlist: rename/delete controls, its entries (loaded once expanded),
 * and the add-entry form. Entries load lazily
 * (`useWatchlistEntriesQuery(expanded ? watchlist.id : null)`) so a page
 * with many watchlists collapsed does not fire an entries request for each
 * of them.
 */
export function WatchlistCard({
  watchlist,
  liveMatchCount,
}: WatchlistCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [nameDraft, setNameDraft] = useState(watchlist.name);
  const [descriptionDraft, setDescriptionDraft] = useState(
    watchlist.description ?? "",
  );
  const [nameTouched, setNameTouched] = useState(false);

  const entriesQuery = useWatchlistEntriesQuery(expanded ? watchlist.id : null);
  const updateMutation = useUpdateWatchlistMutation();
  const deleteMutation = useDeleteWatchlistMutation();
  const addEntryMutation = useAddWatchlistEntryMutation();
  const removeEntryMutation = useRemoveWatchlistEntryMutation();

  const headingId = useId();
  const nameFieldId = useId();
  const descriptionFieldId = useId();

  const nameError = nameTouched ? validateWatchlistName(nameDraft) : null;
  const descriptionError = nameTouched
    ? validateWatchlistDescription(descriptionDraft)
    : null;

  function startRenaming() {
    setNameDraft(watchlist.name);
    setDescriptionDraft(watchlist.description ?? "");
    setNameTouched(false);
    setRenaming(true);
  }

  function handleRenameSubmit(event: React.FormEvent) {
    event.preventDefault();
    setNameTouched(true);
    if (
      validateWatchlistName(nameDraft) !== null ||
      validateWatchlistDescription(descriptionDraft) !== null
    ) {
      return;
    }
    updateMutation.mutate(
      {
        watchlistId: watchlist.id,
        input: {
          name: nameDraft.trim(),
          description:
            descriptionDraft.trim().length > 0 ? descriptionDraft.trim() : null,
        },
      },
      { onSuccess: () => setRenaming(false) },
    );
  }

  function handleDelete() {
    const confirmed = window.confirm(
      `Delete "${watchlist.name}" and all ${watchlist.entry_count} of its entries? This cannot be undone.`,
    );
    if (confirmed) {
      deleteMutation.mutate(watchlist.id);
    }
  }

  const entries = entriesQuery.data?.entries ?? [];
  const addEntryError = addEntryMutation.isError
    ? ((addEntryMutation.error as ApiError | Error).message ??
      "Could not add the entry.")
    : null;

  return (
    <article
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
    >
      {renaming ? (
        <form
          onSubmit={handleRenameSubmit}
          aria-label={`Rename ${watchlist.name}`}
          className="flex flex-col gap-3"
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={nameFieldId}>Name</Label>
            <Input
              id={nameFieldId}
              value={nameDraft}
              aria-invalid={nameError !== null}
              aria-describedby={nameError ? `${nameFieldId}-error` : undefined}
              onChange={(event) => setNameDraft(event.target.value)}
              autoFocus
            />
            <FieldError id={`${nameFieldId}-error`} message={nameError} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={descriptionFieldId}>Description (optional)</Label>
            <Input
              id={descriptionFieldId}
              value={descriptionDraft}
              aria-invalid={descriptionError !== null}
              aria-describedby={
                descriptionError ? `${descriptionFieldId}-error` : undefined
              }
              onChange={(event) => setDescriptionDraft(event.target.value)}
            />
            <FieldError
              id={`${descriptionFieldId}-error`}
              message={descriptionError}
            />
          </div>
          {updateMutation.isError && (
            <p role="alert" className="text-xs text-destructive">
              {errorMessage(updateMutation.error) ??
                "Could not save this watchlist."}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? "Saving…" : "Save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRenaming(false)}
              disabled={updateMutation.isPending}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h3
              id={headingId}
              className="text-base font-semibold tracking-tight"
            >
              {watchlist.name}
            </h3>
            {watchlist.description && (
              <p className="text-sm text-muted-foreground">
                {watchlist.description}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {`${watchlist.entry_count} ${watchlist.entry_count === 1 ? "entry" : "entries"} · ${liveMatchCount} live match${liveMatchCount === 1 ? "" : "es"}`}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={startRenaming}
            >
              Rename
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete"}
            </Button>
          </div>
        </div>
      )}

      {deleteMutation.isError && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage(deleteMutation.error) ??
            "Could not delete this watchlist."}
        </p>
      )}

      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="w-fit"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Hide entries" : "Show entries"}
      </Button>

      {expanded && (
        <div className="flex flex-col gap-3">
          {entriesQuery.isPending && (
            <p className="text-sm text-muted-foreground">Loading entries…</p>
          )}
          {entriesQuery.isError && (
            <p role="alert" className="text-sm text-destructive">
              Could not load entries.
            </p>
          )}

          {entries.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm"
                >
                  <span>
                    <span className="font-medium">
                      {entryKindMeta(entry.kind).label}:{" "}
                    </span>
                    <span>{entry.value}</span>
                    {entry.note && (
                      <span className="text-muted-foreground">{` — ${entry.note}`}</span>
                    )}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive"
                    onClick={() => {
                      removeEntryMutation.mutate({
                        watchlistId: watchlist.id,
                        entryId: entry.id,
                      });
                    }}
                    disabled={
                      removeEntryMutation.isPending &&
                      removeEntryMutation.variables?.entryId === entry.id
                    }
                    aria-label={`Remove ${entryKindMeta(entry.kind).label} entry ${entry.value}`}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}

          <EntryForm
            key={addEntryMutation.data?.id ?? "new-entry"}
            watchlistName={watchlist.name}
            isPending={addEntryMutation.isPending}
            serverError={addEntryError}
            onSubmit={(input) => {
              addEntryMutation.mutate({ watchlistId: watchlist.id, input });
            }}
          />
        </div>
      )}
    </article>
  );
}
