/**
 * Scripted perf guard for the roadmap slice 017 acceptance criterion:
 * "filters compose (AND) and apply within 100 ms in the 500-aircraft
 * demo." `applyFilters` is a single O(n) pass (see its doc comment), so
 * the budget here is set well under the 100 ms AC — the point, as with
 * `frame.perf.test.ts`, is to fail loudly if someone makes this
 * accidentally quadratic, not to police microseconds.
 */

import { describe, expect, it } from "vitest";

import { applyFilters } from "@/features/filters/lib/applyFilters";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import type { LiveAircraft } from "@/lib/api/live";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const AIRCRAFT_COUNT = 500;
const ITERATIONS = 50;
/** The roadmap AC is 100 ms; this asserts a small fraction of it so the
 * test still means something. */
const BUDGET_MS = 20;

function fleet(): LiveAircraft[] {
  const aircraft: LiveAircraft[] = [];
  for (let index = 0; index < AIRCRAFT_COUNT; index += 1) {
    aircraft.push(
      makeAircraft({
        icao: index.toString(16).padStart(6, "0"),
        callsign: `TEST${index}`,
        altitude_ft: 1000 + (index % 40) * 1000,
        distance_nm: index % 300,
        on_ground: index % 13 === 0,
        state: index % 11 === 0 ? "stale" : "live",
        emergency: index % 97 === 0 ? "7700" : null,
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

describe("applyFilters perf", () => {
  it("filters 500 aircraft well inside the 100 ms acceptance criterion", () => {
    const aircraft = fleet();
    const filters = {
      ...DEFAULT_FILTERS,
      altitudeMinFt: 5000,
      altitudeMaxFt: 38000,
      groundTraffic: "dim" as const,
      hideStale: false,
    };
    const config = { displayRadiusNm: 250 };

    const samples: number[] = [];
    for (let iteration = 0; iteration < ITERATIONS; iteration += 1) {
      const began = performance.now();
      applyFilters(aircraft, filters, config);
      samples.push(performance.now() - began);
    }

    const result = median(samples);
    expect(
      result,
      `median filter cost ${result.toFixed(2)} ms for ${AIRCRAFT_COUNT} aircraft`,
    ).toBeLessThanOrEqual(BUDGET_MS);
  });
});
