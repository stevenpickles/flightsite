/**
 * The Sightings page's filter bar: an aircraft search field, a UTC date
 * range, and an "open now" toggle — roadmap slice 030's scope item 2.
 * Uncontrolled `<input>`s that commit on blur/change/submit rather than a
 * value bound to every keystroke, so the URL (and therefore the query)
 * updates once per edit, not once per character.
 *
 * The search field took an exact six-hex-digit ICAO address until slice 083
 * (issue #226); it now takes the start of an ICAO address *or* a callsign —
 * `BAW`, `ae14` — and sends it as `q`. It still shows an exact `icao` that
 * arrived in the URL from a link, and replaces it with `q` once edited. It
 * filters this log only; it is not a global search (SPEC §37/§79).
 */

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  MAX_SEARCH_LENGTH,
  normalizeSearch,
} from "@/features/history/lib/search";
import type { SightingsTableState } from "@/features/sightings/lib/urlState";
import { cn } from "@/lib/utils";

export interface SightingsFiltersProps {
  state: SightingsTableState;
  onChange: (patch: Partial<SightingsTableState>) => void;
}

export function SightingsFilters({ state, onChange }: SightingsFiltersProps) {
  const [searchInput, setSearchInput] = useState(state.q ?? state.icao ?? "");

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = normalizeSearch(searchInput);
    setSearchInput(q ?? "");
    // The box replaces whatever aircraft filter the URL held: a prefix
    // search from here, or none — never both at once.
    onChange({ q, icao: undefined });
  }

  return (
    <div className="mb-4 flex flex-wrap items-end gap-4">
      <form
        role="search"
        aria-label="Filter sightings by aircraft"
        onSubmit={submitSearch}
        className="flex flex-col gap-1"
      >
        <Label htmlFor="sightings-icao-filter">Aircraft or callsign</Label>
        <Input
          id="sightings-icao-filter"
          placeholder="e.g. ae1463 or BAW"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          maxLength={MAX_SEARCH_LENGTH}
          autoComplete="off"
          spellCheck={false}
          aria-describedby="sightings-icao-filter-help"
          className="w-44 font-mono"
        />
        <p
          id="sightings-icao-filter-help"
          className="text-xs text-muted-foreground"
        >
          Start of an ICAO address or callsign; press Enter.
        </p>
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
        state.q !== undefined ||
        state.from !== undefined ||
        state.to !== undefined ||
        state.open) && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className={cn("text-muted-foreground")}
          onClick={() => {
            setSearchInput("");
            onChange({
              icao: undefined,
              q: undefined,
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
