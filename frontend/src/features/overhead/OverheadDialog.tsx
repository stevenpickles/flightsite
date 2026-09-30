/**
 * "What was that?" (roadmap slice 090, issue #233): pick a moment — now by
 * default — and see the aircraft that passed closest to the receiver within
 * a few minutes of it, nearest first, from `GET /api/v1/overhead`.
 *
 * Every row is the aircraft's **closest position fix**: a point its sighting
 * actually stored, with that point's own time and altitude. Nothing between
 * or beyond stored points is interpolated (`docs/API.md` §3.7.1), and the
 * dialog says so under the list — the one caveat a reader needs to trust
 * the distances. This is a single-moment lookup; animated playback stays
 * out of scope (SPEC §79).
 *
 * Times are the receiver's wall clock (SPEC §15), named once by
 * `TimezoneNote`; the picker takes receiver-local time too
 * (`lib/receiverWallTime`). Distances and altitudes follow the receiver's
 * units through the aircraft-detail formatters.
 *
 * Hand-rolled like `ShortcutSheet` (the project ships no dialog primitive):
 * `role="dialog"`, `aria-modal`, `useDialogFocus`'s trap and focus
 * restoration, and Escape handled on the panel so it never also reaches
 * `AircraftDetailPanel`'s window listener. The body mounts only while open,
 * so each opening starts again from "now".
 */
import { Clock, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  formatAltitude,
  formatDegreesWithCardinal,
  formatDistance,
  formatReceiverLocalTime,
  formatReceiverLocalTitle,
} from "@/features/aircraft-detail/lib/format";
import { QueryErrorState } from "@/features/history/components/QueryError";
import { TimezoneNote } from "@/features/history/components/TimezoneNote";
import {
  toWallTimeInput,
  wallTimeInputToIso,
} from "@/features/overhead/lib/receiverWallTime";
import { useOverheadStore } from "@/features/overhead/useOverheadStore";
import type { UnitSystem } from "@/lib/api/config";
import {
  useOverheadQuery,
  type OverheadPass,
  type OverheadResponse,
} from "@/lib/api/overhead";
import { useReceiverQuery } from "@/lib/api/receiver";
import { useDialogFocus } from "@/lib/a11y/useDialogFocus";
import { cn } from "@/lib/utils";

/** The windows offered, in minutes either side of the moment. */
const OVERHEAD_WINDOWS = [5, 10, 30] as const;
type OverheadWindow = (typeof OVERHEAD_WINDOWS)[number];
const DEFAULT_WINDOW: OverheadWindow = 10;
const RESULT_LIMIT = 10;

export function OverheadDialog() {
  const open = useOverheadStore((state) => state.open);
  // Leaving the page that hosts the dialog closes it, so it never reopens
  // by itself on the next page that renders one.
  useEffect(
    () => () => {
      useOverheadStore.getState().close();
    },
    [],
  );
  if (!open) {
    return null;
  }
  return <OverheadDialogBody />;
}

function OverheadDialogBody() {
  const close = useOverheadStore((state) => state.close);
  const headingId = useId();
  const timeId = useId();
  const panelRef = useDialogFocus<HTMLDivElement>({ open: true, modal: true });
  const receiverQuery = useReceiverQuery();
  const timezone = receiverQuery.data?.timezone ?? "UTC";
  const units = receiverQuery.data?.units ?? "aviation";

  const [windowMinutes, setWindowMinutes] =
    useState<OverheadWindow>(DEFAULT_WINDOW);
  /** `null` is "now" — the server's clock, asked afresh on each lookup. */
  const [at, setAt] = useState<string | null>(null);
  /** What the user has typed into the picker, while they are picking. */
  const [typed, setTyped] = useState<string | null>(null);
  const [openedAt] = useState(() => new Date().toISOString());

  const query = useOverheadQuery(
    { at: at ?? undefined, window: windowMinutes, limit: RESULT_LIMIT },
    { enabled: true },
  );

  useEffect(() => {
    panelRef.current?.focus();
  }, [panelRef]);

  // Until the user types, the picker shows the moment the server answered
  // for, on the receiver's clock — and the moment the dialog opened until
  // it has answered.
  const timeInput =
    typed ?? toWallTimeInput(query.data?.at ?? at ?? openedAt, timezone);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={close}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        data-testid="overhead-dialog"
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-xl"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            close();
          }
        }}
      >
        <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 id={headingId} className="text-sm font-semibold">
            What was that?
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close What was that?"
            className="rounded-md p-1.5 text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex shrink-0 flex-col gap-2 border-b border-border px-4 py-3">
          <div className="flex flex-wrap items-end gap-2">
            <label htmlFor={timeId} className="flex flex-col gap-1 text-xs">
              <span className="text-muted-foreground">Around</span>
              <input
                id={timeId}
                type="datetime-local"
                step={60}
                value={timeInput}
                data-testid="overhead-time"
                onChange={(event) => {
                  setTyped(event.target.value);
                  const iso = wallTimeInputToIso(event.target.value, timezone);
                  if (iso !== null) {
                    setAt(iso);
                  }
                }}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm"
              />
            </label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-pressed={at === null}
              onClick={() => {
                if (at === null) {
                  void query.refetch();
                }
                setTyped(null);
                setAt(null);
              }}
            >
              <Clock className="size-3.5" aria-hidden="true" />
              Now
            </Button>
            <div
              role="group"
              aria-label="Window either side"
              className="flex overflow-hidden rounded-md border border-border"
            >
              {OVERHEAD_WINDOWS.map((minutes) => (
                <button
                  key={minutes}
                  type="button"
                  aria-pressed={windowMinutes === minutes}
                  onClick={() => setWindowMinutes(minutes)}
                  className={cn(
                    "h-8 px-2.5 text-xs font-medium outline-none transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                    windowMinutes === minutes
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  ±{minutes} min
                </button>
              ))}
            </div>
          </div>
          <TimezoneNote timezone={timezone} />
        </div>

        <div className="min-h-0 overflow-y-auto px-4 py-3">
          <OverheadResults
            query={query}
            timezone={timezone}
            units={units}
            windowMinutes={windowMinutes}
            onNavigate={close}
          />
        </div>
      </div>
    </div>
  );
}

function OverheadResults({
  query,
  timezone,
  units,
  windowMinutes,
  onNavigate,
}: {
  query: ReturnType<typeof useOverheadQuery>;
  timezone: string;
  units: UnitSystem;
  windowMinutes: number;
  onNavigate: () => void;
}) {
  if (query.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Looking…
      </p>
    );
  }
  if (query.isError) {
    return (
      <QueryErrorState
        message={`Could not look that up: ${query.error.message}`}
        onRetry={() => void query.refetch()}
        isRetrying={query.isFetching}
      />
    );
  }
  const data: OverheadResponse = query.data;
  if (!data.receiver_configured) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        No receiver location is set, so there is nothing to measure from.{" "}
        <Link
          to="/settings"
          onClick={onNavigate}
          className="text-accent hover:underline"
        >
          Set it in Settings
        </Link>
        .
      </p>
    );
  }
  if (data.items.length === 0) {
    return (
      <p
        role="status"
        data-testid="overhead-empty"
        className="text-sm text-muted-foreground"
      >
        Nothing passed within ±{windowMinutes} min of{" "}
        {formatReceiverLocalTime(data.at, timezone)} — no aircraft stored a
        position fix near the receiver in that window.
      </p>
    );
  }
  return (
    <>
      <ol
        data-testid="overhead-results"
        className="flex flex-col divide-y divide-border/60"
      >
        {data.items.map((item, index) => (
          <OverheadRow
            key={item.sighting_id}
            item={item}
            rank={index + 1}
            timezone={timezone}
            units={units}
            onNavigate={onNavigate}
          />
        ))}
      </ol>
      <p className="mt-3 text-xs text-muted-foreground">
        Each distance is to that aircraft&rsquo;s closest position fix stored in
        the window — positions between fixes are never interpolated.
        {data.truncated
          ? " The window was very busy, so only the likeliest candidates were checked."
          : ""}
      </p>
    </>
  );
}

function OverheadRow({
  item,
  rank,
  timezone,
  units,
  onNavigate,
}: {
  item: OverheadPass;
  rank: number;
  timezone: string;
  units: UnitSystem;
  onNavigate: () => void;
}) {
  const name = item.callsign ?? item.registration ?? item.icao.toUpperCase();
  const detail = [
    item.callsign !== null ? item.registration : null,
    item.aircraft_type,
    item.operator,
  ].filter((part): part is string => part !== null && part !== "");
  const altitude =
    formatAltitude(item.altitude_ft, units) ?? "altitude unknown";

  return (
    <li
      data-testid="overhead-row"
      className="flex flex-col gap-0.5 py-2 text-sm first:pt-0 last:pb-0"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate font-medium">
          <span className="mr-1.5 text-xs tabular-nums text-muted-foreground">
            {rank}.
          </span>
          {name}
          {detail.length > 0 && (
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              {detail.join(" · ")}
            </span>
          )}
        </span>
        <span className="shrink-0 font-semibold tabular-nums">
          {formatDistance(item.distance_nm, units)}
        </span>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-muted-foreground">
        <span className="tabular-nums">
          <time
            dateTime={item.fix_at}
            title={formatReceiverLocalTitle(item.fix_at, timezone)}
          >
            {formatReceiverLocalTime(item.fix_at, timezone)}
          </time>
          {" · "}
          {altitude}
          {" · "}
          {formatDegreesWithCardinal(item.bearing_deg)}
          {item.distance_kind === "ground" ? " · ground distance" : ""}
          {item.open ? " · sighting still open" : ""}
        </span>
        <span className="flex gap-3">
          <Link
            to={`/sightings/${item.sighting_id}`}
            onClick={onNavigate}
            className="text-accent hover:underline"
          >
            Sighting
          </Link>
          <Link
            to={`/aircraft/${item.icao}`}
            onClick={onNavigate}
            className="text-accent hover:underline"
          >
            Aircraft
          </Link>
        </span>
      </div>
    </li>
  );
}
