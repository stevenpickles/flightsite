import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import {
  validateWatchlistDescription,
  validateWatchlistName,
} from "@/features/watchlists/lib/validation";
import { useCreateWatchlistMutation } from "@/lib/api/watchlists";

/** The "new watchlist" form at the top of the section — name and an
 * optional description. Clears itself on a successful create. */
export function CreateWatchlistForm() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [touched, setTouched] = useState(false);
  const mutation = useCreateWatchlistMutation();

  const nameId = useId();
  const descriptionId = useId();

  const nameError = touched ? validateWatchlistName(name) : null;
  const descriptionError = touched
    ? validateWatchlistDescription(description)
    : null;
  const serverError = mutation.isError
    ? mutation.error instanceof Error
      ? mutation.error.message
      : "Could not create the watchlist."
    : null;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (
      validateWatchlistName(name) !== null ||
      validateWatchlistDescription(description) !== null
    ) {
      return;
    }
    mutation.mutate(
      {
        name: name.trim(),
        description: description.trim().length > 0 ? description.trim() : null,
      },
      {
        onSuccess: () => {
          setName("");
          setDescription("");
          setTouched(false);
        },
      },
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label="Create a new watchlist"
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={nameId}>Name</Label>
          <Input
            id={nameId}
            value={name}
            placeholder="Local Police"
            aria-invalid={nameError !== null}
            aria-describedby={nameError ? `${nameId}-error` : undefined}
            onChange={(event) => setName(event.target.value)}
          />
          <FieldError id={`${nameId}-error`} message={nameError} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={descriptionId}>Description (optional)</Label>
          <Input
            id={descriptionId}
            value={description}
            aria-invalid={descriptionError !== null}
            aria-describedby={
              descriptionError ? `${descriptionId}-error` : undefined
            }
            onChange={(event) => setDescription(event.target.value)}
          />
          <FieldError
            id={`${descriptionId}-error`}
            message={descriptionError}
          />
        </div>
      </div>
      {serverError && (
        <p role="alert" className="text-xs text-destructive">
          {serverError}
        </p>
      )}
      <div>
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create watchlist"}
        </Button>
      </div>
    </form>
  );
}
