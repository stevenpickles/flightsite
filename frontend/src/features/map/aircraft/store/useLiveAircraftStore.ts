/**
 * The live picture, as the map renders it.
 *
 * One Zustand store holds everything the WebSocket delivers plus the two pieces
 * of UI state that belong to the same picture (which aircraft is selected, and
 * the connection's health). It is written **once per frame**, never once per
 * aircraft: `applySnapshot` and `applyDelta` each build the whole next map and
 * commit it in a single `set`, because at 500 aircraft and 1 Hz a per-aircraft
 * write would mean 500 store notifications and 500 React renders a second for a
 * picture that is drawn once.
 *
 * `applyDelta` implements the application order the protocol pins down
 * (`backend/src/flightsite/api/ws.py`): **`removed`, then `stale`, then
 * `updated`**. Following it leaves the client holding exactly what
 * `GET /api/v1/aircraft/current` would have returned when the frame was built.
 *
 * Records keep two local timestamps alongside the payload, both read from the
 * browser's clock rather than `last_seen` (the receiver's clock, which may be
 * skewed from the browser's):
 *
 * * `receivedAt` — when this object arrived. Dates the *data*: how long ago the
 *   client last heard anything at all about this aircraft.
 * * `positionChangedAt` — when the reported fix last actually moved. Dates the
 *   *position*, which is a different thing entirely, because the backend sends
 *   complete aircraft objects every frame: a delta carrying nothing but a new
 *   RSSI still repeats the last decoded position verbatim.
 *
 * The interpolator dead-reckons from `positionChangedAt`. Anchoring it to
 * `receivedAt` was issue #119: distant aircraft decode a CPR position only
 * every 2-10 s while transmitting Mode S every second, so every intervening
 * delta reset elapsed time to zero and snapped the marker back to the stale
 * fix before it crept forward again.
 */

import { create } from "zustand";

import type { SelectedTrack, TrackPoint } from "@/features/map/aircraft/track";
import {
  appendTrackPoint,
  mergeTrackPoints,
} from "@/features/map/aircraft/track";
import type { LiveAircraft, ReceiverInfo } from "@/lib/api/live";
import type { ConnectionStatus } from "@/lib/ws/liveSocket";
import type { DeltaData, SnapshotData } from "@/lib/ws/protocol";

/** One live aircraft plus the local clock readings that date it. */
export interface LiveAircraftRecord {
  aircraft: LiveAircraft;
  /** `Date.now()` when this object was applied. */
  receivedAt: number;
  /** `Date.now()` when `aircraft.position` last changed — the moment the
   * receiver placed the aircraft where the record now says it is. Carried
   * forward unchanged by every frame that repeats the same fix. */
  positionChangedAt: number;
}

/** An aircraft the server has dropped, kept briefly so it fades out instead of
 * blinking away (SPEC §36 asks for staleness to read visually; a marker that
 * vanishes between frames reads as a glitch). */
export interface DepartingRecord {
  aircraft: LiveAircraft;
  removedAt: number;
}

/** How long a removed aircraft keeps rendering while it fades to nothing. */
export const REMOVAL_FADE_MS = 900;

export interface LiveAircraftState {
  /** Every tracked aircraft, keyed by lower-case ICAO hex. Includes
   * non-positioned (Mode S only) entries — they are part of the live picture
   * even though the map cannot draw them (SPEC §20). */
  aircraft: Record<string, LiveAircraftRecord>;
  /** Recently removed aircraft, mid fade-out. */
  departing: Record<string, DepartingRecord>;
  receiver: ReceiverInfo | null;
  selectedIcao: string | null;
  /** The selected aircraft's track: positions observed since it was selected,
   * under the current sighting's history once `backfillTrack` has merged it
   * in. */
  track: SelectedTrack | null;
  connection: ConnectionStatus;

  applySnapshot: (data: SnapshotData, now?: number) => void;
  applyDelta: (data: DeltaData, now?: number) => void;
  setConnection: (status: ConnectionStatus) => void;
  /** Selects an aircraft (or clears the selection with `null`), restarting
   * track accumulation from the aircraft's current position. */
  selectAircraft: (icao: string | null, now?: number) => void;
  /** Merges the selected aircraft's fetched history under the points watched
   * since selection (issue #133). A no-op unless `icao` is still the aircraft
   * the current track belongs to, which is what discards a response that
   * arrives after the selection moved on. */
  backfillTrack: (icao: string, points: readonly TrackPoint[]) => void;
  /** Returns the store to its initial state — used when the socket is torn
   * down so a remount never renders a picture from a dead connection. */
  reset: () => void;
}

function initialState(): Omit<
  LiveAircraftState,
  | "applySnapshot"
  | "applyDelta"
  | "setConnection"
  | "selectAircraft"
  | "backfillTrack"
  | "reset"
> {
  return {
    aircraft: {},
    departing: {},
    receiver: null,
    selectedIcao: null,
    track: null,
    connection: "connecting",
  };
}

/**
 * Whether `next` reports the aircraft at the same place `previous` did.
 *
 * Coordinate identity is the available signal: the payload has no "this is a
 * fresh decode" flag, and two independent CPR solutions for a moving aircraft
 * do not agree to the last float bit. A change of `position_source` counts as
 * a new fix even at identical coordinates — a different measurement chain
 * placed it there — which costs nothing, since a source flip without motion
 * would only re-anchor an aircraft that is not moving anyway.
 */
function samePosition(previous: LiveAircraft, next: LiveAircraft): boolean {
  const before = previous.position;
  const after = next.position;
  if (before === null || after === null) {
    return before === after;
  }
  return (
    before.lat === after.lat &&
    before.lon === after.lon &&
    previous.position_source === next.position_source
  );
}

/** The record for a freshly delivered aircraft object, inheriting the position
 * anchor from the record it replaces when the fix has not moved. */
function upsert(
  entry: LiveAircraft,
  previous: LiveAircraftRecord | undefined,
  now: number,
): LiveAircraftRecord {
  return {
    aircraft: entry,
    receivedAt: now,
    positionChangedAt:
      previous && samePosition(previous.aircraft, entry)
        ? previous.positionChangedAt
        : now,
  };
}

function pruneDeparting(
  departing: Record<string, DepartingRecord>,
  now: number,
): Record<string, DepartingRecord> {
  const next: Record<string, DepartingRecord> = {};
  for (const [icao, record] of Object.entries(departing)) {
    if (now - record.removedAt < REMOVAL_FADE_MS) {
      next[icao] = record;
    }
  }
  return next;
}

/** The track after this frame: seeded on selection, extended while the selected
 * aircraft keeps reporting a position, and left alone when it does not. */
function extendTrack(
  track: SelectedTrack | null,
  selectedIcao: string | null,
  aircraft: Record<string, LiveAircraftRecord>,
  now: number,
): SelectedTrack | null {
  if (selectedIcao === null) {
    return null;
  }
  const base: SelectedTrack =
    track && track.icao === selectedIcao
      ? track
      : { icao: selectedIcao, points: [] };
  const position = aircraft[selectedIcao]?.aircraft.position;
  if (!position) {
    return base;
  }
  const point: TrackPoint = { lat: position.lat, lon: position.lon, at: now };
  const points = appendTrackPoint(base.points, point);
  return points === base.points ? base : { icao: selectedIcao, points };
}

export const useLiveAircraftStore = create<LiveAircraftState>((set) => ({
  ...initialState(),

  applySnapshot: (data, now = Date.now()) => {
    set((state) => {
      // A snapshot replaces the picture wholesale (§4.2), so the map is rebuilt
      // rather than merged; anything it omits is simply gone. An aircraft that
      // survives the rebuild still keeps its position anchor — a reconnect or
      // a periodic resync is not evidence that the aircraft moved.
      const aircraft: Record<string, LiveAircraftRecord> = {};
      for (const entry of data.aircraft) {
        aircraft[entry.icao] = upsert(entry, state.aircraft[entry.icao], now);
      }
      return {
        aircraft,
        departing: pruneDeparting(state.departing, now),
        receiver: data.receiver ?? state.receiver,
        track: extendTrack(state.track, state.selectedIcao, aircraft, now),
      };
    });
  },

  applyDelta: (data, now = Date.now()) => {
    set((state) => {
      const aircraft = { ...state.aircraft };
      const departing = pruneDeparting(state.departing, now);

      // 1. removed
      for (const icao of data.removed) {
        const record = aircraft[icao];
        if (record) {
          departing[icao] = { aircraft: record.aircraft, removedAt: now };
          delete aircraft[icao];
        }
      }
      // 2. stale — a flag flip on whatever object the client already holds.
      for (const icao of data.stale) {
        const record = aircraft[icao];
        if (record && record.aircraft.state !== "stale") {
          aircraft[icao] = {
            aircraft: { ...record.aircraft, state: "stale" },
            receivedAt: record.receivedAt,
            positionChangedAt: record.positionChangedAt,
          };
        }
      }
      // 3. updated — complete objects, so an upsert with no merge logic. An
      // aircraft that reappears here after being removed in the same batch is
      // restored, which is why this step runs last.
      for (const entry of data.updated) {
        aircraft[entry.icao] = upsert(entry, aircraft[entry.icao], now);
        delete departing[entry.icao];
      }

      return {
        aircraft,
        departing,
        track: extendTrack(state.track, state.selectedIcao, aircraft, now),
      };
    });
  },

  setConnection: (status) => {
    set({ connection: status });
  },

  selectAircraft: (icao, now = Date.now()) => {
    set((state) => {
      if (icao === null) {
        return { selectedIcao: null, track: null };
      }
      return {
        selectedIcao: icao,
        track: extendTrack(null, icao, state.aircraft, now),
      };
    });
  },

  backfillTrack: (icao, points) => {
    set((state) => {
      const track = state.track;
      // The track is keyed by ICAO, so a response for an aircraft the
      // selection has since moved away from finds nothing to merge into and is
      // dropped. Reselecting the *same* aircraft restarts accumulation and
      // does take the backfill again, which is what makes a reselect redraw
      // the whole sighting rather than a single point.
      if (points.length === 0 || !track || track.icao !== icao) {
        return state;
      }
      const merged = mergeTrackPoints(points, track.points);
      // Returning `state` itself, not an empty patch: an unchanged track must
      // not notify the layer's subscription into a pointless redraw.
      return merged === track.points
        ? state
        : { track: { icao, points: merged } };
    });
  },

  reset: () => {
    set(initialState());
  },
}));
