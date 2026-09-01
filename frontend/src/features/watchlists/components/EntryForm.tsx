import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import {
  CATEGORY_OPTIONS,
  ENTRY_KINDS,
  entryKindMeta,
} from "@/features/watchlists/lib/vocabulary";
import {
  validateEntryNote,
  validateEntryValue,
} from "@/features/watchlists/lib/validation";
import type {
  WatchlistEntryCreateInput,
  WatchlistEntryKind,
} from "@/lib/api/watchlists";

const SELECT_CLASSES =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50";

export interface EntryFormProps {
  watchlistName: string;
  onSubmit: (input: WatchlistEntryCreateInput) => void;
  isPending: boolean;
  /** Server-side error for the value just submitted (kind-specific format
   * rejection, or a duplicate), surfaced beside the client-side check. */
  serverError: string | null;
}

/**
 * Add-entry form for one watchlist card: a kind selector plus a
 * kind-specific value input (a picklist for `category`, free text
 * otherwise) and an optional note. Client-side validation
 * (`features/watchlists/lib/validation`) mirrors the backend's format rules
 * so a bad value is caught before the round trip; the backend remains
 * authoritative, and its own rejection (`serverError`) is shown the same way.
 */
export function EntryForm({
  watchlistName,
  onSubmit,
  isPending,
  serverError,
}: EntryFormProps) {
  const [kind, setKind] = useState<WatchlistEntryKind>("icao24");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);

  const kindId = useId();
  const valueId = useId();
  const noteId = useId();

  const meta = entryKindMeta(kind);
  const valueError = touched ? validateEntryValue(kind, value) : null;
  const noteError = touched ? validateEntryNote(note) : null;
  const hasBlockingError =
    validateEntryValue(kind, value) !== null ||
    validateEntryNote(note) !== null;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (hasBlockingError) {
      return;
    }
    onSubmit({
      kind,
      value: value.trim(),
      note: note.trim().length > 0 ? note.trim() : null,
    });
  }

  function handleKindChange(nextKind: WatchlistEntryKind) {
    setKind(nextKind);
    setValue("");
    setTouched(false);
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label={`Add an entry to ${watchlistName}`}
      className="flex flex-col gap-3 rounded-md border border-border bg-background p-3"
    >
      <div className="grid gap-3 sm:grid-cols-[minmax(0,10rem)_1fr]">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={kindId}>Kind</Label>
          <select
            id={kindId}
            className={SELECT_CLASSES}
            value={kind}
            onChange={(event) => {
              handleKindChange(event.target.value as WatchlistEntryKind);
            }}
          >
            {ENTRY_KINDS.map((option) => (
              <option key={option.kind} value={option.kind}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={valueId}>Value</Label>
          {kind === "category" ? (
            <select
              id={valueId}
              className={SELECT_CLASSES}
              value={value}
              aria-invalid={valueError !== null}
              aria-describedby={valueError ? `${valueId}-error` : undefined}
              onChange={(event) => {
                setValue(event.target.value);
              }}
            >
              <option value="" disabled>
                Choose a category…
              </option>
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : (
            <Input
              id={valueId}
              value={value}
              placeholder={meta.placeholder}
              aria-invalid={valueError !== null}
              aria-describedby={valueError ? `${valueId}-error` : undefined}
              onChange={(event) => {
                setValue(event.target.value);
              }}
            />
          )}
          <FieldError
            id={`${valueId}-error`}
            message={valueError ?? serverError}
          />
          {valueError === null && serverError === null && (
            <p className="text-xs text-muted-foreground">{meta.hint}</p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={noteId}>Note (optional)</Label>
        <Input
          id={noteId}
          value={note}
          aria-invalid={noteError !== null}
          aria-describedby={noteError ? `${noteId}-error` : undefined}
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
        <FieldError id={`${noteId}-error`} message={noteError} />
      </div>

      <div>
        <Button type="submit" size="sm" disabled={isPending}>
          {isPending ? "Adding…" : "Add entry"}
        </Button>
      </div>
    </form>
  );
}
