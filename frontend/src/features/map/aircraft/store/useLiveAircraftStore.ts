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
 * * `positionChangedAt` — when the receiver *fixed* the position the record now
 *   reports. Dates the *position*, which is a different thing entirely, because
 *   the backend sends complete aircraft objects every frame: a delta carrying
 *   nothing but a new RSSI still repeats the last decoded position verbatim.
 *
 * The interpolator dead-reckons from `positionChangedAt`. Anchoring it to
 * `receivedAt` was issue #119: distant aircraft decode a CPR position only
 * every 2-10 s while transmitting Mode S every second, so every intervening
 * delta reset elapsed time to zero and snapped the marker back to the stale
 * fix before it crept forward again.
 *
 * **A fix is already old when it arrives** — issue #144, the residual error
 * #119's fix left behind. The decoder needs a CPR pair to place an aircraft, so
 * the position in a frame was measured `seen_pos_s` seconds before the poll
 * that read it, and the poll and the socket add their own second or two on top.
 * Stamping the arrival instant therefore anchored every fix systematically
 * *late*: the projection from fix N had already run past fix N+1's raw
 * coordinates by the time they were drawn, so each new fix stepped the marker
 * backwards before it crept forward again. {@link fixAnchor} instead dates a
 * new fix at `now - seen_pos_s`, the age the decoder itself reports (§3.3,
 * honest since slice 062) — the client-side mirror of that slice's server-side
 * ageing.
 *
 * This keeps the #119 rule that only the browser's clock is read. `seen_pos_s`
 * is a *duration*, not an instant: subtracting it from a browser timestamp
 * never mixes the two clocks, so a receiver hours out of step with the browser
 * changes nothing — the same skew-immunity argument slice 062 made in the other
 * direction.
 *
 * A repeated fix is **not** re-dated, however far its reported age has grown
 * since. The aircraft has not been placed anywhere new, so the anchor it
 * already carries is still exactly when it was placed; letting an ageing
 * `seen_pos_s` push the anchor backwards frame by frame would reintroduce #119
 * inverted — the marker racing ahead of the fix and jerking back on each
 * genuine decode. Only a position that actually changed takes a new anchor.
 */

import { create } from "zustand";

import { INTERPOLATION_MAX_FIX_AGE_MS } from "@/features/map/aircraft/interpolation";
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
  /** On the browser's clock, the moment the receiver placed the aircraft where
   * the record now says it is: the arrival of the frame that first carried this
   * fix, back-dated by the fix's own reported age (see {@link fixAnchor}).
   * Carried forward unchanged by every frame that repeats the same fix. */
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
  /** The selected aircraft's track, as the renderer draws it: positions
   * observed since it was selected, under the current sighting's history once
   * `backfillTrack` has merged it in. */
  track: SelectedTrack | null;
  /**
   * The positions of {@link track} the client watched arrive, without any
   * backfilled history — bookkeeping for the backfill, never drawn.
   *
   * It is the one part of the track the client knows first-hand, and so the
   * only safe base to rebuild from. When a backfill names a different sighting
   * than the one already merged (issue #136: sighting N closes and N+1 opens
   * for the same aircraft inside the query cache's stale window), the history
   * is rebuilt against this rather than piled on top of points that turned out
   * to belong to a sighting that has since closed — no additive merge could
   * ever un-draw those.
   */
  trackLive: TrackPoint[];
  /** The sighting id `track.points` was backfilled from, `null` before any
   * backfill has landed. Bookkeeping for the backfill, never drawn. */
  trackBackfilledFrom: number | null;
  connection: ConnectionStatus;

  applySnapshot: (data: SnapshotData, now?: number) => void;
  applyDelta: (data: DeltaData, now?: number) => void;
  setConnection: (status: ConnectionStatus) => void;
  /** Selects an aircraft (or clears the selection with `null`), restarting
   * track accumulation from the aircraft's current position. Selecting the
   * aircraft that is *already* selected changes nothing at all — see the
   * implementation for why that matters. */
  selectAircraft: (icao: string | null, now?: number) => void;
  /** Merges the selected aircraft's fetched history under the points watched
   * since selection (issue #133). A no-op unless `icao` is still the aircraft
   * the current track belongs to, which is what discards a response that
   * arrives after the selection moved on. `sightingId` says which sighting the
   * path came from, so a backfill can *replace* the history of a sighting that
   * has since closed rather than pile new points on top of it (issue #136). */
  backfillTrack: (
    icao: string,
    sightingId: number,
    points: readonly TrackPoint[],
  ) => void;
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
    trackLive: [],
    trackBackfilledFrom: null,
    connection: "connecting",
  };
}

/** The three fields that move together as the selected aircraft's track: what
 * is drawn, what was watched arriving, and which sighting was merged in. */
interface TrackState {
  track: SelectedTrack | null;
  trackLive: TrackPoint[];
  trackBackfilledFrom: number | null;
}

const NO_TRACK: TrackState = {
  track: null,
  trackLive: [],
  trackBackfilledFrom: null,
};

/** Just the three track fields of a wider state.
 *
 * {@link extendTrack} is spread into a patch alongside freshly rebuilt
 * `aircraft` and `departing` maps, so it must never hand back an object
 * carrying anything else: spreading the whole previous state would put the
 * *old* picture back over the new one. */
function trackStateOf(state: TrackState): TrackState {
  return {
    track: state.track,
    trackLive: state.trackLive,
    trackBackfilledFrom: state.trackBackfilledFrom,
  };
}

/** A track just starting for `icao`, with the drawn points and the live record
 * sharing one empty array — see {@link extendTrack} on why that identity is
 * load-bearing. */
function freshTrack(icao: string): TrackState {
  const points: TrackPoint[] = [];
  return {
    track: { icao, points },
    trackLive: points,
    trackBackfilledFrom: null,
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

/**
 * The most reported fix age this store will honour, in seconds.
 *
 * {@link INTERPOLATION_MAX_FIX_AGE_MS} is the natural bound and not a second
 * arbitrary number: it is the age past which the interpolator stops projecting
 * a fix at all, so back-dating further can only change how long the marker sits
 * frozen, never where it is drawn. Anything above it is a decoder reporting
 * something the map has already given up on — an aircraft heard for minutes
 * without a usable CPR pair, or a malformed age — and clamping keeps such a
 * value from throwing the anchor minutes into the past.
 */
const MAX_REPORTED_FIX_AGE_MS = INTERPOLATION_MAX_FIX_AGE_MS;

/**
 * When the receiver fixed the position `entry` reports, on the browser's clock.
 *
 * The frame arrived at `now`, but the decoder says it placed the aircraft
 * `seen_pos_s` seconds earlier, so that is the anchor (issue #144). A missing,
 * negative or non-finite age falls back to `now`, which is exactly the pre-#144
 * behaviour: without a reported age the arrival instant is the best guess
 * available, and it is the conservative one — it under-projects rather than
 * inventing motion.
 */
function fixAnchor(entry: LiveAircraft, now: number): number {
  const reportedS = entry.seen_pos_s;
  if (reportedS === null || !Number.isFinite(reportedS) || reportedS <= 0) {
    return now;
  }
  return now - Math.min(reportedS * 1000, MAX_REPORTED_FIX_AGE_MS);
}

/** The record for a freshly delivered aircraft object, inheriting the position
 * anchor from the record it replaces when the fix has not moved — a repeated
 * fix keeps the anchor it was given, whatever its reported age has grown to. */
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
        : fixAnchor(entry, now),
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

/**
 * The track after this frame: seeded on selection, extended while the selected
 * aircraft keeps reporting a position, and left alone when it does not.
 *
 * A new position is appended to both lists under the same rules, so `points`
 * always ends with everything `live` holds — the backfill only ever prepends
 * history, and the retention cap drops the oldest, which is history first.
 */
function extendTrack(
  state: TrackState,
  selectedIcao: string | null,
  aircraft: Record<string, LiveAircraftRecord>,
  now: number,
): TrackState {
  if (selectedIcao === null) {
    return NO_TRACK;
  }
  const base: TrackState =
    state.track && state.track.icao === selectedIcao
      ? trackStateOf(state)
      : freshTrack(selectedIcao);
  const position = aircraft[selectedIcao]?.aircraft.position;
  if (!position) {
    return base;
  }
  const point: TrackPoint = { lat: position.lat, lon: position.lon, at: now };
  const trackLive = appendTrackPoint(base.trackLive, point);
  if (trackLive === base.trackLive) {
    return base;
  }
  // Until a backfill has actually put history in front of them, the drawn
  // points *are* the live record — the same array, not a copy of it. That
  // identity is what lets `backfillTrack` recognise a backfill that changed
  // nothing and stay silent. Once the two diverge they are maintained
  // separately, and `points` still always ends with everything `trackLive`
  // holds: a backfill only prepends, and the retention cap drops the oldest.
  const drawn = base.track?.points;
  return {
    track: {
      icao: selectedIcao,
      points:
        drawn === undefined || drawn === base.trackLive
          ? trackLive
          : appendTrackPoint(drawn, point),
    },
    trackLive,
    trackBackfilledFrom: base.trackBackfilledFrom,
  };
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
        ...extendTrack(state, state.selectedIcao, aircraft, now),
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
        ...extendTrack(state, state.selectedIcao, aircraft, now),
      };
    });
  },

  setConnection: (status) => {
    set({ connection: status });
  },

  selectAircraft: (icao, now = Date.now()) => {
    set((state) => {
      // Re-selecting what is already selected is not a selection: it is a
      // second click on the same aircraft, a click arriving from a panel row
      // for the aircraft the map already has selected, or a notification
      // jumping to it. Restarting accumulation there would throw away the
      // backfilled history (issue #133) and collapse the trail to a single
      // point, with nothing to rebuild it — the backfill keys off a *change*
      // of selection, and this is not one.
      if (icao === state.selectedIcao) {
        return state;
      }
      if (icao === null) {
        return { selectedIcao: null, ...NO_TRACK };
      }
      return {
        selectedIcao: icao,
        ...extendTrack(NO_TRACK, icao, state.aircraft, now),
      };
    });
  },

  backfillTrack: (icao, sightingId, points) => {
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
      // Which base to merge onto is the whole of issue #136. For the sighting
      // already merged, `points` is the same path grown at its newest end —
      // ground `trackLive` already covers — so merging onto the drawn track is
      // additive and settles to a no-op. For a *different* sighting the drawn
      // track holds a path that has turned out to belong to a sighting that
      // closed, and no additive merge can remove it: rebuild from `trackLive`,
      // the only part the client watched first-hand, and the stale points are
      // simply not carried over.
      const sameSighting = state.trackBackfilledFrom === sightingId;
      const base = sameSighting ? track.points : state.trackLive;
      const merged = mergeTrackPoints(points, base);
      // Returning `state` itself, not an empty patch: an unchanged track must
      // not notify the layer's subscription into a pointless redraw. The
      // sighting id is deliberately not recorded in that case — nothing from
      // this sighting is drawn, so there is nothing for a later response to
      // treat as already merged.
      if (merged === track.points) {
        return state;
      }
      return {
        track: { icao, points: merged },
        trackBackfilledFrom: sightingId,
      };
    });
  },

  reset: () => {
    set(initialState());
  },
}));
