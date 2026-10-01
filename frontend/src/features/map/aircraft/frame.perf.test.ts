/**
 * Scripted perf guard for the JavaScript half of the 500-aircraft target.
 *
 * Roadmap slice 014's acceptance criterion is ">= 30 fps with no interaction
 * frame > 100 ms" on a 500-aircraft demo. That is a *rendering* claim, and it
 * can only be settled against a real GPU and a real renderer — the visual and
 * performance work in slice 049 owns that measurement.
 *
 * What this test owns is the part that is FlightSite's own code and that a
 * jsdom run can measure honestly: the data-building path from a delta frame to
 * the GeoJSON handed to `setData` — store application, dead reckoning, icon
 * resolution, feature construction. MapLibre's parsing, tiling, and painting
 * are deliberately outside the measured window (the source's `setData` is a
 * no-op here), because timing a mock would measure nothing.
 *
 * The budget is 10 ms median per frame for 500 aircraft. At the ~12.5 fps this
 * layer redraws at (`FRAME_INTERVAL_MS`), that is an eighth of the frame
 * budget left to the renderer, and it is a generous multiple of what the path
 * actually costs — the point is to fail loudly if someone makes it
 * quadratic, not to police a few hundred microseconds.
 *
 * Roadmap slice 085 holds its all-aircraft trails to the *same* budget, not a
 * separate one: a trailed frame is still one frame, and the budget is what
 * the renderer is promised it will be left with.
 */

import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it } from "vitest";

import { AIRCRAFT_TRAILS_SOURCE_ID } from "@/features/map/aircraft/aircraftLayers";
import { drawAircraftFrame } from "@/features/map/aircraft/frame";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { resetTrails, TRAIL_MAX_POINTS } from "@/features/map/aircraft/trails";
import type { LiveAircraft } from "@/lib/api/live";
import { makeAircraft } from "@/test/liveAircraftFixtures";

/** The scale SPEC §5 and the roadmap size the live picture for. */
const AIRCRAFT_COUNT = 500;
const FRAMES = 40;
const BUDGET_MS = 10;

/** A map whose sources accept data and do nothing with it, so the measurement
 * covers FlightSite's code and not a test double's bookkeeping. */
const NULL_MAP = {
  getSource: () => ({ setData: () => undefined }),
  getZoom: () => 10,
} as unknown as MapLibreGlMap;

function fleet(tick: number): LiveAircraft[] {
  const aircraft: LiveAircraft[] = [];
  for (let index = 0; index < AIRCRAFT_COUNT; index += 1) {
    aircraft.push(
      makeAircraft({
        icao: index.toString(16).padStart(6, "0"),
        callsign: `TEST${index}`,
        position: {
          lat: 40 + (index % 50) / 10 + tick / 1000,
          lon: -125 + Math.floor(index / 50) / 10,
        },
        track_deg: (index * 7) % 360,
        ground_speed_kt: 180 + (index % 300),
        position_source: index % 5 === 0 ? "mlat" : "adsb",
        state: index % 11 === 0 ? "stale" : "live",
        on_ground: index % 13 === 0,
      }),
    );
  }
  return aircraft;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2
    : (sorted[middle] ?? 0);
}

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
  resetTrails();
});

describe("500-aircraft frame cost", () => {
  it("builds a frame's GeoJSON well inside the budget", () => {
    const store = useLiveAircraftStore.getState();
    const start = Date.now();
    store.applySnapshot({ aircraft: fleet(0), receiver: null }, start);
    store.selectAircraft("000001");

    const samples: number[] = [];
    for (let tick = 1; tick <= FRAMES; tick += 1) {
      const now = start + tick * 1000;
      const updated = fleet(tick);
      const began = performance.now();
      // The whole per-frame path: apply the delta, then rebuild and push both
      // sources (the store-driven redraw, which is the expensive variant).
      useLiveAircraftStore
        .getState()
        .applyDelta({ updated, stale: [], removed: [] }, now);
      drawAircraftFrame(NULL_MAP, useLiveAircraftStore.getState(), now, {
        includeTrack: true,
      });
      samples.push(performance.now() - began);
    }

    const result = median(samples);
    expect(
      result,
      `median frame cost ${result.toFixed(2)} ms for ${AIRCRAFT_COUNT} aircraft`,
    ).toBeLessThanOrEqual(BUDGET_MS);
  });

  it("builds a frame with every aircraft trailed well inside the same budget", () => {
    // Roadmap slice 085's acceptance criterion: all-aircraft trails at 500
    // aircraft keep the Live Map frame-time budget. Run past the point cap
    // (FRAMES > TRAIL_MAX_POINTS) so every trail is at its longest — 499
    // full trails (the selected aircraft draws its track instead), ~15,000
    // vertices — for the samples that matter most, and measure the
    // store-driven redraw that is the only one to rebuild them.
    expect(FRAMES).toBeGreaterThan(TRAIL_MAX_POINTS);
    const store = useLiveAircraftStore.getState();
    const start = Date.now();
    store.applySnapshot({ aircraft: fleet(0), receiver: null }, start);
    store.selectAircraft("000001");

    let trailFeatures = 0;
    let trailVertices = 0;
    const map = {
      getSource: (id: string) => ({
        setData: (data: {
          features?: { geometry: { coordinates: unknown[] } }[];
        }) => {
          if (id === AIRCRAFT_TRAILS_SOURCE_ID) {
            trailFeatures = data.features?.length ?? 0;
            trailVertices = 0;
            for (const feature of data.features ?? []) {
              trailVertices += feature.geometry.coordinates.length;
            }
          }
        },
      }),
      getZoom: () => 10,
    } as unknown as MapLibreGlMap;

    const samples: number[] = [];
    for (let tick = 1; tick <= FRAMES; tick += 1) {
      const now = start + tick * 1000;
      const updated = fleet(tick);
      const began = performance.now();
      useLiveAircraftStore
        .getState()
        .applyDelta({ updated, stale: [], removed: [] }, now);
      drawAircraftFrame(map, useLiveAircraftStore.getState(), now, {
        includeTrack: true,
        includeTrails: true,
        trailsEnabled: true,
      });
      samples.push(performance.now() - began);
    }

    // Guards the guard: the trails really were built, at full length.
    expect(trailFeatures).toBe(AIRCRAFT_COUNT - 1);
    expect(trailVertices).toBe((AIRCRAFT_COUNT - 1) * TRAIL_MAX_POINTS);

    const result = median(samples);
    expect(
      result,
      `median frame cost ${result.toFixed(2)} ms for ${AIRCRAFT_COUNT} trailed aircraft`,
    ).toBeLessThanOrEqual(BUDGET_MS);
  });

  it("emits a feature for every positioned aircraft", () => {
    // Guards the guard: a frame that silently built nothing would be fast.
    const now = Date.now();
    useLiveAircraftStore
      .getState()
      .applySnapshot({ aircraft: fleet(0), receiver: null }, now);

    let features = 0;
    drawAircraftFrame(
      {
        getSource: () => ({
          setData: (data: { features?: unknown[] }) => {
            features = data.features?.length ?? 0;
          },
        }),
        getZoom: () => 10,
      } as unknown as MapLibreGlMap,
      useLiveAircraftStore.getState(),
      now,
    );
    expect(features).toBe(AIRCRAFT_COUNT);
  });
});
