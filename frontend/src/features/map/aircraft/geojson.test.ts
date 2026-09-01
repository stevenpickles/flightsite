import { describe, expect, it } from "vitest";

import type { AircraftFrameInput } from "@/features/map/aircraft/geojson";
import {
  buildAircraftFeatureCollection,
  buildTrackFeatureCollection,
  STALE_OPACITY,
} from "@/features/map/aircraft/geojson";
import { iconImageId } from "@/features/map/aircraft/icons/silhouettes";
import type {
  DepartingRecord,
  LiveAircraftRecord,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import { REMOVAL_FADE_MS } from "@/features/map/aircraft/store/useLiveAircraftStore";
import {
  DENSITY_CALLSIGN_THRESHOLD,
  ZOOM_LABELS_FULL,
  ZOOM_LABELS_MIN,
} from "@/features/map/labels/priority";
import type { LiveAircraft } from "@/lib/api/live";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const NOW = 1_800_000_000_000;

function records(
  ...entries: Partial<LiveAircraft>[]
): Record<string, LiveAircraftRecord> {
  const map: Record<string, LiveAircraftRecord> = {};
  for (const entry of entries) {
    const aircraft = makeAircraft(entry);
    map[aircraft.icao] = { aircraft, receivedAt: NOW };
  }
  return map;
}

function input(
  overrides: Partial<AircraftFrameInput> = {},
): AircraftFrameInput {
  return {
    aircraft: {},
    departing: {},
    selectedIcao: null,
    now: NOW,
    ...overrides,
  };
}

function propertiesByIcao(
  collection: ReturnType<typeof buildAircraftFeatureCollection>,
) {
  return Object.fromEntries(
    collection.features.map((feature) => [
      feature.properties.icao,
      feature.properties,
    ]),
  );
}

describe("buildAircraftFeatureCollection", () => {
  it("emits a point per positioned aircraft at lon/lat order", () => {
    const collection = buildAircraftFeatureCollection(
      input({
        aircraft: records({
          icao: "aaaaaa",
          position: { lat: 47.6, lon: -122.3 },
          ground_speed_kt: null,
        }),
      }),
    );
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.features).toHaveLength(1);
    expect(collection.features[0]?.geometry.coordinates).toEqual([
      -122.3, 47.6,
    ]);
  });

  it("omits non-positioned aircraft", () => {
    // Mode S only: part of the live picture (SPEC §20), not of the map layer.
    const collection = buildAircraftFeatureCollection(
      input({
        aircraft: records({
          icao: "aaaaaa",
          position: null,
          position_source: "none",
        }),
      }),
    );
    expect(collection.features).toHaveLength(0);
  });

  it("publishes the reported track for icon-rotate", () => {
    const collection = buildAircraftFeatureCollection(
      input({ aircraft: records({ icao: "aaaaaa", track_deg: 217 }) }),
    );
    expect(collection.features[0]?.properties.track).toBe(217);
  });

  it("draws an aircraft with no reported track unrotated", () => {
    const collection = buildAircraftFeatureCollection(
      input({ aircraft: records({ icao: "aaaaaa", track_deg: null }) }),
    );
    expect(collection.features[0]?.properties.track).toBe(0);
  });

  it("resolves the icon through the hierarchy", () => {
    const collection = buildAircraftFeatureCollection(
      input({
        aircraft: records(
          { icao: "aaaaaa", on_ground: false },
          { icao: "bbbbbb", on_ground: true, ground_speed_kt: 8 },
        ),
      }),
    );
    const properties = propertiesByIcao(collection);
    expect(properties.aaaaaa?.icon).toBe(iconImageId("airliner"));
    expect(properties.bbbbbb?.icon).toBe(iconImageId("ground"));
    expect(properties.bbbbbb?.onGround).toBe(true);
  });

  it("fades stale aircraft instead of hiding them", () => {
    // SPEC §36: stale aircraft visually fade.
    const collection = buildAircraftFeatureCollection(
      input({ aircraft: records({ icao: "aaaaaa", state: "stale" }) }),
    );
    expect(collection.features[0]?.properties.stale).toBe(true);
    expect(collection.features[0]?.properties.opacity).toBe(STALE_OPACITY);
  });

  it("flags MLAT positions so the dashed ring layer can filter on them", () => {
    const collection = buildAircraftFeatureCollection(
      input({
        aircraft: records(
          { icao: "aaaaaa", position_source: "mlat" },
          { icao: "bbbbbb", position_source: "adsb" },
        ),
      }),
    );
    const properties = propertiesByIcao(collection);
    expect(properties.aaaaaa?.mlat).toBe(true);
    expect(properties.bbbbbb?.mlat).toBe(false);
  });

  it("marks exactly the selected aircraft", () => {
    const collection = buildAircraftFeatureCollection(
      input({
        aircraft: records({ icao: "aaaaaa" }, { icao: "bbbbbb" }),
        selectedIcao: "bbbbbb",
      }),
    );
    const properties = propertiesByIcao(collection);
    expect(properties.aaaaaa?.selected).toBe(false);
    expect(properties.bbbbbb?.selected).toBe(true);
  });

  it("carries the callsign through for later label slices", () => {
    const collection = buildAircraftFeatureCollection(
      input({ aircraft: records({ icao: "aaaaaa", callsign: "BAW123" }) }),
    );
    expect(collection.features[0]?.properties.callsign).toBe("BAW123");
  });

  it("interpolates a moving aircraft forward from its last report", () => {
    const aircraft = records({
      icao: "aaaaaa",
      position: { lat: 0, lon: 0 },
      track_deg: 0,
      ground_speed_kt: 360,
    });
    const collection = buildAircraftFeatureCollection(
      input({ aircraft, now: NOW + 1000 }),
    );
    const [lon, lat] = collection.features[0]?.geometry.coordinates ?? [];
    expect(lon).toBeCloseTo(0, 9);
    expect(lat).toBeCloseTo(0.1 / 60, 9);
  });

  it("does not interpolate a stale aircraft", () => {
    const aircraft = records({
      icao: "aaaaaa",
      state: "stale",
      position: { lat: 0, lon: 0 },
      track_deg: 0,
      ground_speed_kt: 360,
    });
    const collection = buildAircraftFeatureCollection(
      input({ aircraft, now: NOW + 3000 }),
    );
    expect(collection.features[0]?.geometry.coordinates).toEqual([0, 0]);
  });

  describe("removal fade", () => {
    const departing = (removedAt: number): Record<string, DepartingRecord> => ({
      aaaaaa: {
        aircraft: makeAircraft({
          icao: "aaaaaa",
          position: { lat: 1, lon: 2 },
        }),
        removedAt,
      },
    });

    it("keeps a removed aircraft on the map while it fades", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          departing: departing(NOW - REMOVAL_FADE_MS / 2),
        }),
      );
      expect(collection.features).toHaveLength(1);
      expect(collection.features[0]?.properties.opacity).toBeCloseTo(
        STALE_OPACITY / 2,
        6,
      );
      expect(collection.features[0]?.properties.stale).toBe(true);
    });

    it("drops it once the fade has finished", () => {
      const collection = buildAircraftFeatureCollection(
        input({ departing: departing(NOW - REMOVAL_FADE_MS) }),
      );
      expect(collection.features).toHaveLength(0);
    });

    it("never moves a removed aircraft", () => {
      // The fixture reports 450 kt on a 090 track, so an interpolated feature
      // would have moved east. The server has said it is gone; projecting it
      // would be invention.
      const collection = buildAircraftFeatureCollection(
        input({ departing: departing(NOW - 400) }),
      );
      expect(collection.features[0]?.geometry.coordinates).toEqual([2, 1]);
    });

    it("skips a removed aircraft that never had a position", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          departing: {
            aaaaaa: {
              aircraft: makeAircraft({ icao: "aaaaaa", position: null }),
              removedAt: NOW,
            },
          },
        }),
      );
      expect(collection.features).toHaveLength(0);
    });
  });

  describe("labels", () => {
    it("carries an interesting flag from the aircraft's active alert match", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          aircraft: records(
            { icao: "aaaaaa", interesting: null },
            {
              icao: "bbbbbb",
              interesting: { severity: "high", reasons: ["test"] },
            },
          ),
          zoom: ZOOM_LABELS_FULL,
        }),
      );
      const properties = propertiesByIcao(collection);
      expect(properties.aaaaaa?.interesting).toBe(false);
      expect(properties.bbbbbb?.interesting).toBe(true);
    });

    it("shows no label below the minimum labeling zoom", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          aircraft: records({ icao: "aaaaaa", callsign: "BAW123" }),
          zoom: ZOOM_LABELS_MIN - 1,
        }),
      );
      expect(collection.features[0]?.properties.label).toBe("");
    });

    it("shows callsign only between the minimum and full labeling zoom", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          aircraft: records({
            icao: "aaaaaa",
            callsign: "BAW123",
            altitude_ft: 35000,
          }),
          zoom: ZOOM_LABELS_MIN,
        }),
      );
      expect(collection.features[0]?.properties.label).toBe("BAW123");
    });

    it("shows the full stack at and above the full labeling zoom", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          aircraft: records({
            icao: "aaaaaa",
            callsign: "BAW123",
            altitude_ft: 35000,
          }),
          zoom: ZOOM_LABELS_FULL,
        }),
      );
      expect(collection.features[0]?.properties.label).toBe("BAW123\nFL350");
    });

    it("drops a non-priority label to callsign-only when the live picture is dense, even at high zoom", () => {
      const dense = records(
        ...Array.from({ length: DENSITY_CALLSIGN_THRESHOLD + 1 }, (_, i) => ({
          icao: i.toString(16).padStart(6, "0"),
          callsign: `AA${i}`,
          altitude_ft: 35000,
        })),
      );
      const collection = buildAircraftFeatureCollection(
        input({ aircraft: dense, zoom: ZOOM_LABELS_FULL }),
      );
      for (const feature of collection.features) {
        expect(feature.properties.label).toBe(feature.properties.callsign);
      }
    });

    it("always fully labels the selected aircraft, even below the minimum zoom", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          aircraft: records({
            icao: "aaaaaa",
            callsign: "BAW123",
            altitude_ft: 35000,
          }),
          selectedIcao: "aaaaaa",
          zoom: ZOOM_LABELS_MIN - 1,
        }),
      );
      expect(collection.features[0]?.properties.label).toBe("BAW123\nFL350");
    });

    it("always fully labels an interesting aircraft, even when the picture is dense", () => {
      const dense = records(
        {
          icao: "aaaaaa",
          callsign: "BAW123",
          altitude_ft: 35000,
          interesting: { severity: "high", reasons: ["test"] },
        },
        ...Array.from({ length: DENSITY_CALLSIGN_THRESHOLD }, (_, i) => ({
          icao: (i + 1).toString(16).padStart(6, "0"),
          callsign: `AA${i}`,
        })),
      );
      const collection = buildAircraftFeatureCollection(
        input({ aircraft: dense, zoom: ZOOM_LABELS_FULL }),
      );
      const properties = propertiesByIcao(collection);
      // Full stack, indicator-prefixed — the interesting flag both forces
      // the tier and prefixes line 1 (`labelContent.ts`).
      expect(properties.aaaaaa?.label).toBe("★ BAW123\nFL350");
    });

    it("falls back through registration and then ICAO for line 1", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          aircraft: records({
            icao: "abcdef",
            callsign: null,
            registration: "N12345",
          }),
          zoom: ZOOM_LABELS_MIN,
        }),
      );
      expect(collection.features[0]?.properties.label).toBe("N12345");
    });

    it("defaults zoom to the full-label band when omitted", () => {
      // `input()` never sets `zoom` unless a test overrides it — this pins
      // the default `buildAircraftFeatureCollection` itself falls back to.
      const collection = buildAircraftFeatureCollection(
        input({ aircraft: records({ icao: "aaaaaa", callsign: "BAW123" }) }),
      );
      expect(collection.features[0]?.properties.label).toContain("BAW123");
    });

    it("never labels a departing (fading) aircraft", () => {
      const collection = buildAircraftFeatureCollection(
        input({
          departing: {
            aaaaaa: {
              aircraft: makeAircraft({
                icao: "aaaaaa",
                position: { lat: 1, lon: 2 },
                callsign: "BAW123",
              }),
              removedAt: NOW - 100,
            },
          },
          zoom: ZOOM_LABELS_FULL,
        }),
      );
      expect(collection.features[0]?.properties.label).toBe("");
      expect(collection.features[0]?.properties.interesting).toBe(false);
    });
  });
});

describe("buildTrackFeatureCollection", () => {
  it("is empty with no selection", () => {
    expect(buildTrackFeatureCollection(null).features).toHaveLength(0);
  });

  it("is empty until two positions have been observed", () => {
    expect(
      buildTrackFeatureCollection({
        icao: "aaaaaa",
        points: [{ lat: 1, lon: 2, at: NOW }],
      }).features,
    ).toHaveLength(0);
  });

  it("emits one LineString in observation order", () => {
    const collection = buildTrackFeatureCollection({
      icao: "aaaaaa",
      points: [
        { lat: 1, lon: 2, at: NOW },
        { lat: 3, lon: 4, at: NOW + 1000 },
      ],
    });
    expect(collection.features).toHaveLength(1);
    expect(collection.features[0]?.geometry.coordinates).toEqual([
      [2, 1],
      [4, 3],
    ]);
    expect(collection.features[0]?.properties.icao).toBe("aaaaaa");
  });
});
