/**
 * The Sightings page's filter bar: an exact-ICAO search field, a UTC date
 * range, and an "open now" toggle — roadmap slice 030's scope item 2.
 * Uncontrolled `<input>`s that commit on blur/change/submit rather than a
 * value bound to every keystroke, so the URL (and therefore the query)
 * updates once per edit, not once per character.
 */

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SightingsTableState } from "@/features/sightings/lib/urlState";
import { cn } from "@/lib/utils";

const ICAO_PATTERN = /^[0-9a-f]{6}$/i;

export interface SightingsFiltersProps {
  state: SightingsTableState;
  onChange: (patch: Partial<SightingsTableState>) => void;
}

export function SightingsFilters({ state, onChange }: SightingsFiltersProps) {
  const [icaoInput, setIcaoInput] = useState(state.icao ?? "");
  const [icaoInvalid, setIcaoInvalid] = useState(false);

  function submitIcao(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = icaoInput.trim().toLowerCase();
    if (trimmed.length === 0) {
      setIcaoInvalid(false);
      onChange({ icao: undefined });
      return;
    }
    if (!ICAO_PATTERN.test(trimmed)) {
      setIcaoInvalid(true);
      return;
    }
    setIcaoInvalid(false);
    setIcaoInput(trimmed);
    onChange({ icao: trimmed });
  }

  return (
    <div className="mb-4 flex flex-wrap items-end gap-4">
      <form onSubmit={submitIcao} className="flex flex-col gap-1">
        <Label htmlFor="sightings-icao-filter">Aircraft (ICAO)</Label>
        <Input
          id="sightings-icao-filter"
          placeholder="e.g. ae1463"
          value={icaoInput}
          onChange={(event) => setIcaoInput(event.target.value)}
          aria-invalid={icaoInvalid}
          className="w-36 font-mono"
        />
        {icaoInvalid && (
          <p className="text-xs text-destructive">
            Enter a 6-character hex ICAO address.
          </p>
        )}
      </form>

      <div className="flex flex-col gap-1">
        <Label htmlFor="sightings-from-filter">From</Label>
        <Input
          id="sightings-from-filter"
          type="date"
          value={state.from ?? ""}
          onChange={(event) =>
            onChange({
              from: event.target.value === "" ? undefined : event.target.value,
            })
          }
          className="w-40"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="sightings-to-filter">To</Label>
        <Input
          id="sightings-to-filter"
          type="date"
          value={state.to ?? ""}
          onChange={(event) =>
            onChange({
              to: event.target.value === "" ? undefined : event.target.value,
            })
          }
          className="w-40"
        />
      </div>

      <Button
        type="button"
        variant={state.open ? "accent" : "outline"}
        size="sm"
        aria-pressed={state.open}
        onClick={() => onChange({ open: !state.open })}
      >
        Open now
      </Button>

      {(state.icao !== undefined ||
        state.from !== undefined ||
        state.to !== undefined ||
        state.open) && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn("text-muted-foreground")}
          onClick={() => {
            setIcaoInput("");
            setIcaoInvalid(false);
            onChange({
              icao: undefined,
              from: undefined,
              to: undefined,
              open: false,
            });
          }}
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}
