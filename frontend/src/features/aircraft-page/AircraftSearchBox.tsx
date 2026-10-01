/**
 * The Aircraft page's filter box (roadmap slice 083, issue #226): find an
 * airframe by the identifier you remember — the start of its ICAO address,
 * registration, any callsign it has flown, type or operator. It waits for
 * {@link MIN_SEARCH_LENGTH} characters before searching.
 *
 * It filters *this list* and nothing else. A search box that also answered
 * sightings, alerts or places would be SPEC §79's deferred global search,
 * which this deliberately is not (§37: search is scoped to the list page).
 *
 * The input is local state; the URL (`q`, beside `sort`/`order`/`page`) is
 * written {@link SEARCH_DEBOUNCE_MS} after the last keystroke, so typing
 * "G-EZTH" issues one request rather than six. Enter and the clear button
 * commit at once — the user has said they are done. When the URL changes
 * underneath the box (back button, a shared link, "Back to page 1"), the box
 * follows it.
 */

import { Search, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  isTooShort,
  MAX_SEARCH_LENGTH,
  MIN_SEARCH_LENGTH,
  normalizeSearch,
} from "@/features/aircraft-page/lib/urlState";

/** Idle time after the last keystroke before the search reaches the URL. */
export const SEARCH_DEBOUNCE_MS = 250;

export interface AircraftSearchBoxProps {
  /** The committed search — the URL's `q`. */
  value: string | undefined;
  /** Commits a new search (already normalized), or `undefined` to clear. */
  onChange: (q: string | undefined) => void;
}

export function AircraftSearchBox({ value, onChange }: AircraftSearchBoxProps) {
  const [draft, setDraft] = useState(value ?? "");
  const [followed, setFollowed] = useState(value);

  // Follow a URL change made elsewhere — adjusting state during render, as
  // React recommends over an effect, so the box never shows a stale value
  // for a frame. A change this box committed itself already matches the
  // draft and leaves it (and the caret) alone.
  if (value !== followed) {
    setFollowed(value);
    if (normalizeSearch(draft) !== value) {
      setDraft(value ?? "");
    }
  }

  // The latest `onChange` without making it a dependency of the timer: a
  // parent re-rendering mid-debounce (the list polls) must not restart it.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  const next = normalizeSearch(draft);
  // One character is held back: no request, a hint instead, and whatever
  // search is already committed stays until there is a better one.
  const tooShort = isTooShort(next);

  useEffect(() => {
    if (next === value || tooShort) {
      return undefined;
    }
    const timer = setTimeout(() => {
      onChangeRef.current(next);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [next, tooShort, value]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (next !== value && !tooShort) {
      onChange(next);
    }
  }

  function clear() {
    setDraft("");
    if (value !== undefined) {
      onChange(undefined);
    }
  }

  return (
    <form
      role="search"
      aria-label="Filter aircraft"
      onSubmit={submit}
      className="mb-4 flex flex-col gap-1"
    >
      <Label htmlFor="aircraft-search">Filter aircraft</Label>
      <div className="relative w-full max-w-md">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id="aircraft-search"
          type="text"
          inputMode="search"
          autoComplete="off"
          spellCheck={false}
          maxLength={MAX_SEARCH_LENGTH}
          placeholder="e.g. G-EZ, BAW, a1b2, B738"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          aria-describedby="aircraft-search-help"
          className="pl-8 pr-9"
        />
        {draft !== "" && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Clear filter"
            onClick={clear}
            className="absolute right-0 top-1/2 -translate-y-1/2 text-muted-foreground"
          >
            <X aria-hidden="true" className="size-4" />
          </Button>
        )}
      </div>
      <p id="aircraft-search-help" className="text-xs text-muted-foreground">
        Starts with an ICAO address, registration, callsign, type or operator.
        Not case-sensitive.
      </p>
      <p role="status" className="min-h-4 text-xs text-muted-foreground">
        {tooShort ? `Type at least ${MIN_SEARCH_LENGTH} characters.` : ""}
      </p>
    </form>
  );
}
