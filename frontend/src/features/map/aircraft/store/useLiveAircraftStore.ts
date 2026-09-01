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
 * Records keep `receivedAt` alongside the payload. That timestamp — not
 * `last_seen`, which is the receiver's clock and may be skewed from the
 * browser's — is the base the interpolator dead-reckons from.
 */

import { create } from "zustand";

import type { SelectedTrack, TrackPoint } from "@/features/map/aircraft/track";
import { appendTrackPoint } from "@/features/map/aircraft/track";
import type { LiveAircraft, ReceiverInfo } from "@/lib/api/live";
import type { ConnectionStatus } from "@/lib/ws/liveSocket";
import type { DeltaData, SnapshotData } from "@/lib/ws/protocol";

/** One live aircraft plus the local clock reading that dates it. */
export interface LiveAircraftRecord {
  aircraft: LiveAircraft;
  /** `Date.now()` when this object was applied. */
  receivedAt: number;
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
  /** Positions observed for the selected aircraft since it was selected. */
  track: SelectedTrack | null;
  connection: ConnectionStatus;

  applySnapshot: (data: SnapshotData, now?: number) => void;
  applyDelta: (data: DeltaData, now?: number) => void;
  setConnection: (status: ConnectionStatus) => void;
  /** Selects an aircraft (or clears the selection with `null`), restarting
   * track accumulation from the aircraft's current position. */
  selectAircraft: (icao: string | null, now?: number) => void;
  /** Returns the store to its initial state — used when the socket is torn
   * down so a remount never renders a picture from a dead connection. */
  reset: () => void;
}

function initialState(): Omit<
  LiveAircraftState,
  "applySnapshot" | "applyDelta" | "setConnection" | "selectAircraft" | "reset"
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
      // rather than merged; anything it omits is simply gone.
      const aircraft: Record<string, LiveAircraftRecord> = {};
      for (const entry of data.aircraft) {
        aircraft[entry.icao] = { aircraft: entry, receivedAt: now };
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
          };
        }
      }
      // 3. updated — complete objects, so an upsert with no merge logic. An
      // aircraft that reappears here after being removed in the same batch is
      // restored, which is why this step runs last.
      for (const entry of data.updated) {
        aircraft[entry.icao] = { aircraft: entry, receivedAt: now };
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

  reset: () => {
    set(initialState());
  },
}));
