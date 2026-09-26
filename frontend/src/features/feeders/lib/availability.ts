/**
 * Pure layout math for `GapTimeline` (roadmap slice 077, design record
 * "Frontend"): turns a feeder's episode history into a run of
 * left-to-right, non-overlapping segments positioned as percentages of a
 * fixed window, so the component can render a bar without doing any of its
 * own date arithmetic.
 *
 * Kept free of React and of `Date.now()` (the caller passes `now`) for the
 * same reason `features/receiver/lib/chartOptions.ts` stays a pure
 * function of its inputs — this can be asserted against fixed fixtures
 * without a fake clock or a mounted component
 * (`docs/TEST_STRATEGY.md` favors testing logic over rendering where the
 * two can be separated).
 *
 * `GET /api/v1/feeders/{name}/history` already returns its own
 * `availability_pct` for the window (design record "API"), but that number
 * describes only the episodes the backend recorded — it says nothing about
 * a window that starts before any episode exists (a feeder added partway
 * through the window, or a fresh install). {@link buildAvailabilitySegments}
 * fills exactly that silence with an explicit `"unknown"` segment rather
 * than leaving a blank stretch of bar, and {@link computeAvailabilityPct}
 * derives the displayed percentage from those same segments so the number
 * next to the bar can never disagree with the bar itself.
 */
import type { FeederEpisode, FeederState } from "@/lib/api/feeders";

export type AvailabilityWindow = "24h" | "7d" | "30d";

export const AVAILABILITY_WINDOWS: readonly AvailabilityWindow[] = [
  "24h",
  "7d",
  "30d",
];

export const AVAILABILITY_WINDOW_LABEL: Record<AvailabilityWindow, string> = {
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
};

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

const WINDOW_DURATION_MS: Record<AvailabilityWindow, number> = {
  "24h": DAY_MS,
  "7d": 7 * DAY_MS,
  "30d": 30 * DAY_MS,
};

export function windowDurationMs(window: AvailabilityWindow): number {
  return WINDOW_DURATION_MS[window];
}

export interface AvailabilitySegment {
  state: FeederState;
  startedAt: string;
  endedAt: string;
  /** Percentage of the window's width from its left edge, 0–100. */
  startPct: number;
  /** Percentage of the window's width this segment spans, > 0–100. */
  widthPct: number;
}

function clampMs(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function toSegment(
  state: FeederState,
  startMs: number,
  endMs: number,
  windowStartMs: number,
  durationMs: number,
): AvailabilitySegment {
  return {
    state,
    startedAt: new Date(startMs).toISOString(),
    endedAt: new Date(endMs).toISOString(),
    startPct: ((startMs - windowStartMs) / durationMs) * 100,
    widthPct: ((endMs - startMs) / durationMs) * 100,
  };
}

/**
 * Builds the ordered, gap-filled segment run for one feeder's episodes over
 * `window`, ending at `now`.
 *
 * Episodes are clipped to `[now - windowDuration, now]`; anything entirely
 * outside that range is dropped. Any stretch of the window no episode
 * covers — including an in-progress episode's open end (`ended_at: null`,
 * clipped to `now`) — becomes an explicit `"unknown"` segment rather than a
 * silent hole in the bar.
 */
export function buildAvailabilitySegments(
  episodes: readonly FeederEpisode[],
  window: AvailabilityWindow,
  now: Date,
): AvailabilitySegment[] {
  const nowMs = now.getTime();
  const durationMs = windowDurationMs(window);
  const windowStartMs = nowMs - durationMs;

  const clipped = episodes
    .map((episode) => {
      const rawStart = new Date(episode.started_at).getTime();
      const rawEnd =
        episode.ended_at === null
          ? nowMs
          : new Date(episode.ended_at).getTime();
      return {
        state: episode.state,
        startMs: clampMs(rawStart, windowStartMs, nowMs),
        endMs: clampMs(rawEnd, windowStartMs, nowMs),
      };
    })
    .filter(
      (episode) =>
        Number.isFinite(episode.startMs) &&
        Number.isFinite(episode.endMs) &&
        episode.endMs > episode.startMs,
    )
    .sort((a, b) => a.startMs - b.startMs);

  const segments: AvailabilitySegment[] = [];
  let cursor = windowStartMs;

  for (const episode of clipped) {
    if (episode.startMs > cursor) {
      segments.push(
        toSegment(
          "unknown",
          cursor,
          episode.startMs,
          windowStartMs,
          durationMs,
        ),
      );
    }
    const start = Math.max(episode.startMs, cursor);
    if (episode.endMs > start) {
      segments.push(
        toSegment(
          episode.state,
          start,
          episode.endMs,
          windowStartMs,
          durationMs,
        ),
      );
      cursor = episode.endMs;
    } else {
      cursor = Math.max(cursor, episode.startMs);
    }
  }

  if (cursor < nowMs) {
    segments.push(
      toSegment("unknown", cursor, nowMs, windowStartMs, durationMs),
    );
  }

  return segments;
}

export interface Availability {
  /** Share of the *observed* span spent `"up"`, 0–100; `null` when nothing
   * in the window was observed at all. */
  pct: number | null;
  /** How much of the window FlightSite actually watched this feeder. */
  observedMs: number;
  /** The window's full length, for "of N observed" wording. */
  windowMs: number;
}

/** Availability over the part of the window that was actually observed —
 * derived from the same segments the bar renders, so the number and the
 * picture can never disagree (see module docstring).
 *
 * The denominator is the observed span, not the window: a feeder watched for
 * three minutes of a 24-hour window and up for all of them is 100 % available
 * "of 3 m observed", not 0.2 % available. Scoring the unobserved stretch as
 * downtime would blame the feeder for FlightSite's own absence, which is the
 * kind of confident wrong number the 2026-09-20 site review was about. */
export function computeAvailability(
  segments: readonly AvailabilitySegment[],
  window: AvailabilityWindow,
): Availability {
  const windowMs = windowDurationMs(window);
  let upWidthPct = 0;
  let observedWidthPct = 0;
  for (const segment of segments) {
    if (segment.state === "unknown") continue;
    observedWidthPct += segment.widthPct;
    if (segment.state === "up") upWidthPct += segment.widthPct;
  }
  const observedMs = Math.round((observedWidthPct / 100) * windowMs);
  if (observedWidthPct <= 0) {
    return { pct: null, observedMs: 0, windowMs };
  }
  return {
    pct: clampMs((upWidthPct / observedWidthPct) * 100, 0, 100),
    observedMs,
    windowMs,
  };
}

/** {@link computeAvailability}'s percentage alone; `null` when unobserved. */
export function computeAvailabilityPct(
  segments: readonly AvailabilitySegment[],
  window: AvailabilityWindow = "24h",
): number | null {
  return computeAvailability(segments, window).pct;
}
