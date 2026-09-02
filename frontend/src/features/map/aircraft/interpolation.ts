/**
 * Position smoothing between position fixes.
 *
 * The socket delivers a batch about once a second (`docs/API.md` §4.3). Drawn
 * as-is, a 450 kt airliner jumps ~0.13 nm at a time — clearly a stutter at any
 * useful zoom. Between fixes each aircraft is therefore dead-reckoned along its
 * last reported velocity: `track_deg` for direction, `ground_speed_kt` for
 * rate, and the store's `positionChangedAt` for elapsed time.
 *
 * **Why `positionChangedAt` and not `receivedAt`.** The two are not
 * interchangeable, and treating them as such was issue #119. Every frame
 * carries a *complete* aircraft object, so a delta reporting nothing but a new
 * RSSI still repeats the last decoded position verbatim. A distant aircraft
 * decodes a CPR position only every 2-10 s while transmitting Mode S every
 * second, so anchoring to `receivedAt` reset elapsed time to zero several times
 * between fixes: the marker crept forward, snapped back to the stale fix, and
 * crept forward again. Elapsed time has to be measured from the moment the
 * position was *fixed*, which is what the store now records.
 *
 * **And the fix was already old when it arrived** — issue #144. The store dates
 * a new fix at `receivedAt - seen_pos_s * 1000`, the decoder's own age for the
 * CPR solution converted from seconds to the milliseconds these timestamps are
 * kept in, rather than at the instant the frame landed; see
 * `useLiveAircraftStore` for the dating rules and why a *repeated* fix is never
 * re-dated. That is what makes this projection continuous across fixes. With
 * both anchors honest, the projection running from fix N at the moment fix N+1
 * lands and the projection starting from fix N+1 are the same point for an
 * aircraft flying straight: N+1's coordinates sit behind N's projection by
 * exactly the travel N+1's own age immediately adds back. Whatever poll and
 * socket latency the frames share cancels in the subtraction, so it need not be
 * known — only the part of the delay the decoder measures differs between
 * fixes, and that is the part `seen_pos_s` reports. Dating both fixes at
 * arrival instead dropped the age term from one side only, which is why the
 * marker stepped back by (fix age × ground speed) on every decode.
 *
 * A back-dated fix is therefore projected forward the moment it arrives, with
 * `elapsed` already positive. That is the intent, not an edge case: `elapsed`
 * asks how long the aircraft has been flying since it was placed, and the
 * answer at arrival is `seen_pos_s`, not zero. The `elapsed === 0` shortcut
 * below still covers what it always covered — no time to project, so nothing
 * to compute.
 *
 * **Why dead reckoning rather than tweening between the last two positions.**
 * Tweening is smooth but wrong twice over: it renders the aircraft a full
 * update *behind* where it was last reported, and it needs two positions, which
 * a newly appeared aircraft does not have. Projecting forward from the latest
 * fix keeps the marker at the receiver's best estimate of *now*, and the next
 * fix simply supersedes it. Reported values are never modified — the detail
 * panel and every other consumer read the payload, not this projection.
 *
 * **Bounds.** Two limits, because the correct anchor separated two questions
 * the old single cap had conflated.
 *
 * {@link INTERPOLATION_MAX_FIX_AGE_MS} asks *how stale is this fix?* An
 * aircraft heard every second but not positioned for a minute — Mode S with no
 * usable CPR pair — stays `live`, and projecting it indefinitely would fly it
 * across the map on the strength of a velocity nothing has confirmed.
 *
 * {@link INTERPOLATION_STALL_GRACE_MS} asks *is the stream still running?* A
 * suspended tab, a dead backend or a client mid-reconnect stops all frames, and
 * a projection that kept advancing would be inventing motion out of a
 * disconnect. It is measured from `receivedAt`, which is exactly the question
 * that timestamp answers.
 *
 * Both caps freeze the marker where the projection had reached; neither rewinds
 * it to the raw fix, since a rewind is the visible defect this module exists to
 * avoid. Stale aircraft are not projected at all: staleness means the receiver
 * has stopped hearing them, so their last known position is the honest thing to
 * draw.
 *
 * **No correction blend on a new fix**, considered and declined in slice 054
 * and re-examined in 064. A new fix still moves the marker by however far the
 * projection had drifted, and easing into it instead of snapping is the obvious
 * next refinement. Slice 054 declined it on the grounds that the step is only
 * the dead-reckoning error over one fix interval — metres for an aircraft
 * flying straight, against the ~0.8 nm the #119 anchor jumped. That was the
 * right conclusion from a premise that was not yet true: the anchor was still
 * late by the fix's own age, leaving a systematic step of (fix age × ground
 * speed), ~0.1-0.3 nm at jet speeds and reliably backwards, which is the
 * oscillation issue #144 reported. Back-dating removes that term rather than
 * masking it, and what remains is the error the paragraph always claimed —
 * genuine manoeuvring between fixes, near the noise floor for straight flight,
 * and not systematically signed. So the blend stays declined, now on its stated
 * grounds. The cost is real, too. This function is pure and
 * called once per aircraft per frame; a blend needs the previously *drawn*
 * position kept per aircraft between frames, which means mutable render state
 * with its own eviction, reset-on-reconnect and store-reset invalidation. And
 * during the ease it would deliberately draw the aircraft behind the receiver's
 * best estimate — the same objection that rules out tweening above.
 *
 * The flat-earth conversion (1 nm = 1/60°, longitude scaled by cos φ) is exact
 * enough by orders of magnitude at these distances: one second at 600 kt is
 * 0.17 nm, where the error against a great-circle projection is well under a
 * metre outside the polar regions the `cos φ` clamp already guards.
 */

import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { GeoPosition } from "@/lib/api/live";

/**
 * How far past its last position fix an aircraft may be dead-reckoned.
 *
 * Sized against the backend's own definition of "still being heard":
 * `sighting.stale_s` defaults to 15 s (`config.example.yaml`), after which an
 * aircraft is marked `stale` and this module stops projecting it outright. A
 * fix older than that interval has outlived the silence the backend treats as
 * losing an aircraft altogether, so it is a fair place to stop inventing
 * motion — while comfortably covering the 2-10 s CPR cadence of a distant
 * aircraft, which is the case that has to project smoothly.
 *
 * The predecessor of this constant was 4 s, which was correct against the old
 * per-delta anchor and far too short against this one: it would re-freeze a
 * distant aircraft for most of every gap between fixes, reintroducing the
 * stutter from the other side.
 *
 * Since slice 064 this measures the fix's *true* age — the store's anchor now
 * includes the decode age the frame arrived with (issue #144) — which is what
 * the bound always meant. It reads a few seconds sooner in wall-clock terms
 * than it used to, and correctly so: an aircraft last placed 15 s ago is
 * equally unfit to project whether the client learned that 15 s ago or 5 s ago.
 * The same constant doubles as the store's clamp on a reported age, since a fix
 * older than this is not projected anyway.
 */
export const INTERPOLATION_MAX_FIX_AGE_MS = 15_000;

/**
 * How far past the last delivered frame the projection may keep running.
 *
 * Four seconds is a few missed deltas at 1 Hz — enough to ride out a hiccup,
 * short enough that a genuinely dead stream freezes rather than inventing
 * motion. This is the bound the old `INTERPOLATION_MAX_MS` was really
 * enforcing; it survives unchanged, now measured against the timestamp that
 * actually tracks stream liveness.
 */
export const INTERPOLATION_STALL_GRACE_MS = 4_000;

/** Nautical miles per degree of latitude. */
const NM_PER_DEGREE = 60;

const MS_PER_HOUR = 3_600_000;

/** Keeps the longitude scaling finite near the poles (cos φ → 0). At 89.4°
 * the scale factor is already ~100×, past which "smoothing" is noise. */
const MIN_COS_LATITUDE = 0.01;

const DEG_TO_RAD = Math.PI / 180;

/** Wraps a longitude back into [-180, 180) so a projection across the
 * antimeridian produces a drawable coordinate rather than 181°. */
export function normalizeLongitude(lon: number): number {
  const wrapped = (((lon + 180) % 360) + 360) % 360;
  return wrapped - 180;
}

/**
 * The position reached by travelling `elapsedMs` from `from` on a constant
 * `trackDeg` heading at `groundSpeedKt`.
 *
 * @param trackDeg - degrees clockwise from true north.
 */
export function projectPosition(
  from: GeoPosition,
  trackDeg: number,
  groundSpeedKt: number,
  elapsedMs: number,
): GeoPosition {
  const distanceNm = (groundSpeedKt * elapsedMs) / MS_PER_HOUR;
  const radians = trackDeg * DEG_TO_RAD;
  const deltaLat = (distanceNm * Math.cos(radians)) / NM_PER_DEGREE;
  const cosLat = Math.max(
    MIN_COS_LATITUDE,
    Math.abs(Math.cos(from.lat * DEG_TO_RAD)),
  );
  const deltaLon = (distanceNm * Math.sin(radians)) / (NM_PER_DEGREE * cosLat);
  return {
    lat: Math.max(-90, Math.min(90, from.lat + deltaLat)),
    lon: normalizeLongitude(from.lon + deltaLon),
  };
}

/**
 * Where to draw `record` at `now`: its projected position when it is airborne,
 * live, moving and positioned; its reported position otherwise; `null` when it
 * has no position at all (a Mode S-only entry, SPEC §20 — part of the live
 * picture, but not something the map can place).
 */
export function displayPosition(
  record: LiveAircraftRecord,
  now: number,
): GeoPosition | null {
  const { aircraft, receivedAt, positionChangedAt } = record;
  const position = aircraft.position;
  if (!position) {
    return null;
  }
  if (aircraft.state === "stale" || aircraft.on_ground === true) {
    return position;
  }
  const { track_deg: track, ground_speed_kt: speed } = aircraft;
  if (track === null || speed === null || speed <= 0) {
    return position;
  }
  // Advance the clock no further than the last frame plus its grace: past that
  // the stream has stalled, and the projection holds where it had reached
  // rather than running on or rewinding.
  const advanceUntil = Math.min(now, receivedAt + INTERPOLATION_STALL_GRACE_MS);
  const elapsed = Math.min(
    INTERPOLATION_MAX_FIX_AGE_MS,
    Math.max(0, advanceUntil - positionChangedAt),
  );
  if (elapsed === 0) {
    return position;
  }
  return projectPosition(position, track, speed, elapsed);
}
