/**
 * Short trails for every visible aircraft (roadmap slice 085, issue #228).
 *
 * The selected aircraft already has a *track* (`track.ts`): its whole current
 * sighting, backfilled from history, the thing SPEC §19 asks the app to keep.
 * A trail is something else — a few seconds of wake behind every other
 * aircraft, so the picture shows where things are heading without selecting
 * each one. It is aircraft rendering, not a map overlay (SPEC §33 caps those
 * at airports, airspace and range rings), and it is off by default.
 *
 * ## Bounds, and why these
 *
 * Each aircraft keeps at most {@link TRAIL_MAX_POINTS} positions, none older
 * than {@link TRAIL_MAX_AGE_MS}. Two caps because each one alone fails a
 * case the other catches:
 *
 * - **30 points** bounds the memory and the per-frame cost outright: 500
 *   aircraft x 30 points is 15,000 vertices, whatever the feed does. At the
 *   ~1 Hz ADS-B position rate that is about half a minute of flight — at
 *   450 kt, a little under 4 nm, a clear heading cue at the zooms where
 *   individual aircraft are legible without turning a busy picture into
 *   spaghetti.
 * - **2 minutes** bounds the *time* a trail can span. An MLAT or weak-signal
 *   contact may fix its position a handful of times a minute, and a count cap
 *   alone would then draw a line through the last half hour of its flight. A
 *   stale aircraft (no new fixes) sees its trail drain away point by point as
 *   the old ones age out, rather than dragging a fixed tail behind a contact
 *   that is no longer moving on the map.
 *
 * ## Where the memory lives
 *
 * One module-level {@link TrailBuffer}, {@link liveTrails}, owned by the frame
 * loop exactly as `labels/densityLatch.ts` owns the density latch — and for
 * the same reason: there is one live picture per tab, the frame loop is the
 * one imperative path that draws it in sequence, and the GeoJSON builder
 * (`geojson.ts`'s `buildTrailFeatureCollection`) stays pure by only ever
 * *reading* the buffer it is handed. `frame.ts` feeds it; `AircraftLayer`
 * clears it on unmount.
 *
 * The buffer is fed from the live store's records, never from interpolated
 * display positions: a trail is where the receiver *placed* the aircraft,
 * and dead-reckoned points would be invention. A point is recorded once per
 * fix — keyed on the record's `positionChangedAt`, which a repeated fix
 * carries forward unchanged — so feeding the buffer more often than the
 * picture changes is harmless.
 *
 * **Memory is bounded when aircraft leave.** Every {@link TrailBuffer.record}
 * drops the ring of any ICAO no longer in the live store, so a removed
 * aircraft's trail disappears with it (a departing aircraft's fade-out draws
 * no trail — it is no longer part of the live picture) and the buffer never
 * holds more rings than the store holds aircraft.
 */

import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";

/** Most positions any one aircraft's trail keeps — see the module docstring. */
export const TRAIL_MAX_POINTS = 30;

/** Oldest position a trail keeps, in milliseconds — see the module
 * docstring. */
export const TRAIL_MAX_AGE_MS = 2 * 60 * 1000;

/**
 * One aircraft's recent positions, as a fixed-capacity ring over three typed
 * arrays: appending never allocates, and dropping the oldest point is an
 * index bump rather than an `Array.shift`. At 500 aircraft that is the
 * difference between a steady ~360 KB and a small allocation per aircraft
 * per second for the garbage collector to chase.
 */
interface TrailRing {
  lats: Float64Array;
  lons: Float64Array;
  /** Browser-clock milliseconds the position was fixed at. */
  ats: Float64Array;
  /** Index of the oldest retained point. */
  start: number;
  /** How many points are retained, `0..TRAIL_MAX_POINTS`. */
  length: number;
}

function createRing(): TrailRing {
  return {
    lats: new Float64Array(TRAIL_MAX_POINTS),
    lons: new Float64Array(TRAIL_MAX_POINTS),
    ats: new Float64Array(TRAIL_MAX_POINTS),
    start: 0,
    length: 0,
  };
}

function slot(ring: TrailRing, offset: number): number {
  return (ring.start + offset) % TRAIL_MAX_POINTS;
}

/** Drops points older than `cutoff` from the front of the ring. */
function expire(ring: TrailRing, cutoff: number): void {
  while (ring.length > 0 && (ring.ats[ring.start] as number) < cutoff) {
    ring.start = (ring.start + 1) % TRAIL_MAX_POINTS;
    ring.length -= 1;
  }
}

/** The read side of a {@link TrailBuffer} — everything the pure GeoJSON
 * builder needs, and nothing that can change it. */
export interface TrailSource {
  /**
   * `icao`'s retained positions no older than `now - TRAIL_MAX_AGE_MS`,
   * oldest first, as `[lon, lat]` pairs ready for a GeoJSON LineString.
   * Empty for an aircraft with no trail.
   */
  coordinates(icao: string, now: number): [number, number][];
}

export class TrailBuffer implements TrailSource {
  private readonly rings = new Map<string, TrailRing>();

  /**
   * Folds the live picture into the trails as of `now`:
   *
   * 1. appends each positioned aircraft's current fix, unless it is the fix
   *    already at the head of its trail (same `positionChangedAt`) or an
   *    older one;
   * 2. expires every trail's points older than {@link TRAIL_MAX_AGE_MS};
   * 3. forgets every aircraft no longer in `aircraft`, and every trail that
   *    expiry emptied.
   *
   * One pass over the store plus one over the buffer: O(aircraft).
   */
  record(aircraft: Record<string, LiveAircraftRecord>, now: number): void {
    const cutoff = now - TRAIL_MAX_AGE_MS;
    for (const icao in aircraft) {
      const record = aircraft[icao];
      const position = record?.aircraft.position;
      if (!record || !position) {
        continue;
      }
      const at = record.positionChangedAt;
      if (at < cutoff) {
        continue;
      }
      let ring = this.rings.get(icao);
      if (!ring) {
        ring = createRing();
        this.rings.set(icao, ring);
      } else if (
        ring.length > 0 &&
        (ring.ats[slot(ring, ring.length - 1)] as number) >= at
      ) {
        continue;
      }
      if (ring.length === TRAIL_MAX_POINTS) {
        // Full: the new point overwrites the oldest.
        ring.start = (ring.start + 1) % TRAIL_MAX_POINTS;
        ring.length -= 1;
      }
      const index = slot(ring, ring.length);
      ring.lats[index] = position.lat;
      ring.lons[index] = position.lon;
      ring.ats[index] = at;
      ring.length += 1;
    }

    for (const [icao, ring] of this.rings) {
      if (!(icao in aircraft)) {
        this.rings.delete(icao);
        continue;
      }
      expire(ring, cutoff);
      if (ring.length === 0) {
        this.rings.delete(icao);
      }
    }
  }

  coordinates(icao: string, now: number): [number, number][] {
    const ring = this.rings.get(icao);
    if (!ring) {
      return [];
    }
    const cutoff = now - TRAIL_MAX_AGE_MS;
    const out: [number, number][] = [];
    for (let offset = 0; offset < ring.length; offset += 1) {
      const index = slot(ring, offset);
      if ((ring.ats[index] as number) < cutoff) {
        continue;
      }
      out.push([ring.lons[index] as number, ring.lats[index] as number]);
    }
    return out;
  }

  /** How many aircraft currently hold a trail — for the memory-bound tests. */
  get size(): number {
    return this.rings.size;
  }

  /** How many points `icao`'s trail currently retains. */
  pointCount(icao: string): number {
    return this.rings.get(icao)?.length ?? 0;
  }

  clear(): void {
    this.rings.clear();
  }
}

/** The live map's trails — see the module docstring. */
export const liveTrails = new TrailBuffer();

/** Forgets every trail. `AircraftLayer` calls this on unmount, beside
 * `resetDensityLatch`: the trails are memory about frames the map drew, and
 * a remount should start from the picture, not from an old wake. */
export function resetTrails(): void {
  liveTrails.clear();
}
