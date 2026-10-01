import { X } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";

export interface ChipsInputProps {
  /** The visible label of the text box new chips are typed into. */
  label: string;
  values: readonly string[];
  onChange: (next: string[]) => void;
  /** Why one typed entry cannot become a chip, or `null`. */
  validate: (raw: string) => string | null;
  /** Applied to an entry before it is validated and added (e.g. upper-case). */
  normalize?: (raw: string) => string;
  /** How a chip reads — the code alone by default. */
  formatChip?: (value: string) => string;
  /** Offered as the text box's autocomplete list. */
  suggestions?: readonly { value: string; label: string }[];
  placeholder?: string;
  /** The condition-level error's id, so the box is described by it too. */
  describedBy?: string;
  invalid?: boolean;
}

/**
 * A set of short codes edited as removable chips (roadmap slice 089's
 * squawk and emitter-category conditions).
 *
 * Type a code and press Enter, a comma or the Add button; several separated
 * by spaces or commas are added at once, which is what pasting "1200 7000"
 * expects. Backspace in an empty box removes the last chip, and every chip
 * has its own named remove button, so the whole control works from the
 * keyboard. An entry that is not a valid code is refused on the spot with a
 * message naming the format — unlike the rest of the builder, which waits
 * for a submit: a refused chip is input that was *not* taken, and saying so
 * only later would look like it had been. Leaving the box with a valid
 * entry still in it adds it, so a typed-but-not-entered code is not lost on
 * submit.
 */
export function ChipsInput({
  label,
  values,
  onChange,
  validate,
  normalize = (raw) => raw.trim(),
  formatChip = (value) => value,
  suggestions,
  placeholder,
  describedBy,
  invalid = false,
}: ChipsInputProps) {
  const inputId = useId();
  const listId = `${inputId}-suggestions`;
  const entryErrorId = `${inputId}-entry-error`;
  const [entry, setEntry] = useState("");
  const [entryError, setEntryError] = useState<string | null>(null);

  function commit(raw: string): boolean {
    const tokens = raw
      .split(/[\s,]+/)
      .map(normalize)
      .filter((token) => token.length > 0);
    if (tokens.length === 0) {
      return true;
    }
    for (const token of tokens) {
      const error = validate(token);
      if (error) {
        setEntryError(error);
        return false;
      }
    }
    const next = [...values];
    for (const token of tokens) {
      if (!next.includes(token)) {
        next.push(token);
      }
    }
    onChange(next);
    setEntry("");
    setEntryError(null);
    return true;
  }

  const describedByIds =
    [describedBy, entryError ? entryErrorId : undefined]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={inputId}>{label}</Label>
      {values.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={`${label}: added`}>
          {values.map((value) => (
            <li
              key={value}
              className="flex items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5 text-xs text-foreground"
            >
              <span>{formatChip(value)}</span>
              <button
                type="button"
                className="rounded-full p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                aria-label={`Remove ${value}`}
                onClick={() => {
                  onChange(values.filter((existing) => existing !== value));
                }}
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Input
          id={inputId}
          value={entry}
          placeholder={placeholder}
          list={suggestions ? listId : undefined}
          aria-invalid={invalid || entryError !== null}
          aria-describedby={describedByIds}
          onChange={(event) => {
            setEntry(event.target.value);
            setEntryError(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              commit(entry);
            } else if (
              event.key === "Backspace" &&
              entry.length === 0 &&
              values.length > 0
            ) {
              onChange(values.slice(0, -1));
            }
          }}
          onBlur={() => {
            if (
              entry.trim().length > 0 &&
              validate(normalize(entry)) === null
            ) {
              commit(entry);
            }
          }}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            commit(entry);
          }}
        >
          Add
        </Button>
      </div>
      {suggestions && (
        <datalist id={listId}>
          {suggestions.map((suggestion) => (
            <option key={suggestion.value} value={suggestion.value}>
              {suggestion.label}
            </option>
          ))}
        </datalist>
      )}
      <FieldError id={entryErrorId} message={entryError} />
    </div>
  );
}
