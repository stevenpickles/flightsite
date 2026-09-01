import { describe, expect, it } from "vitest";

import { describeSightingEvent } from "@/features/sighting-detail/lib/eventDescriptions";
import type { SightingEvent } from "@/lib/api/sightings";

function event(overrides: Partial<SightingEvent> = {}): SightingEvent {
  return {
    at: "2026-08-30T22:10:00.000Z",
    type: "callsign_change",
    detail: null,
    ...overrides,
  };
}

describe("describeSightingEvent", () => {
  it("describes a callsign change with the from/to detail", () => {
    const info = describeSightingEvent(
      event({ type: "callsign_change", detail: { from: "N1", to: "N2" } }),
    );
    expect(info.label).toBe("Callsign changed");
    expect(info.detail).toBe("N1 → N2");
  });

  it("describes a squawk change with the from/to detail", () => {
    const info = describeSightingEvent(
      event({
        type: "squawk_change",
        detail: { from: "2000", to: "4521" },
      }),
    );
    expect(info.label).toBe("Squawk changed");
    expect(info.detail).toBe("2000 → 4521");
  });

  it("describes an emergency start with its squawk", () => {
    const info = describeSightingEvent(
      event({ type: "emergency_start", detail: { squawk: "7700" } }),
    );
    expect(info.label).toBe("Emergency declared");
    expect(info.detail).toBe("Squawk 7700");
  });

  it("describes an emergency end with its squawk", () => {
    const info = describeSightingEvent(
      event({ type: "emergency_end", detail: { squawk: "4521" } }),
    );
    expect(info.label).toBe("Emergency cleared");
    expect(info.detail).toBe("Squawk 4521");
  });

  it("describes route enrichment with the route and its source", () => {
    const info = describeSightingEvent(
      event({
        type: "route_enriched",
        detail: { source: "aerodatabox", origin: "KTCM", destination: "PHIK" },
      }),
    );
    expect(info.label).toBe("Route enriched");
    expect(info.detail).toBe("KTCM → PHIK · aerodatabox");
  });

  it("describes route enrichment with only one leg known", () => {
    const info = describeSightingEvent(
      event({
        type: "route_enriched",
        detail: { source: "aerodatabox", origin: "KTCM", destination: null },
      }),
    );
    expect(info.detail).toBe("KTCM → ? · aerodatabox");
  });

  it("describes classification/alert events with a label and no detail", () => {
    expect(
      describeSightingEvent(event({ type: "classification_available" })),
    ).toEqual({
      label: "Classification became available",
      detail: null,
    });
    expect(describeSightingEvent(event({ type: "alert_matched" }))).toEqual({
      label: "Alert matched",
      detail: null,
    });
    expect(
      describeSightingEvent(event({ type: "alert_severity_upgraded" })),
    ).toEqual({
      label: "Alert severity upgraded",
      detail: null,
    });
  });

  it("falls back gracefully when a detail is missing entirely", () => {
    const info = describeSightingEvent(
      event({ type: "callsign_change", detail: null }),
    );
    expect(info.label).toBe("Callsign changed");
    expect(info.detail).toBeNull();
  });
});
