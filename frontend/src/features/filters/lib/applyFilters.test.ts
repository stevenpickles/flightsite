import { describe, expect, it } from "vitest";

import {
  applyFilters,
  passesFilters,
} from "@/features/filters/lib/applyFilters";
import { DEFAULT_FILTERS, type LiveFilters } from "@/features/filters/types";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const CONFIG = { displayRadiusNm: 250 };

function filters(overrides: Partial<LiveFilters> = {}): LiveFilters {
  return { ...DEFAULT_FILTERS, ...overrides };
}

describe("applyFilters", () => {
  it("passes everything through the default filter set", () => {
    const aircraft = [
      makeAircraft({ icao: "aaaaaa" }),
      makeAircraft({ icao: "bbbbbb", position: null, distance_nm: null }),
    ];
    const result = applyFilters(aircraft, DEFAULT_FILTERS, CONFIG);
    expect(result.aircraft).toHaveLength(2);
    expect(result.visibleIcaos).toEqual(new Set(["aaaaaa", "bbbbbb"]));
    expect(result.dimmedIcaos.size).toBe(0);
    expect(result.distanceCappedCount).toBe(0);
    expect(result.effectiveDistanceCapNm).toBe(250);
  });

  describe("altitude range", () => {
    it("excludes below the minimum", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", altitude_ft: 1000 })];
      const result = applyFilters(
        aircraft,
        filters({ altitudeMinFt: 5000 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("excludes above the maximum", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", altitude_ft: 40000 })];
      const result = applyFilters(
        aircraft,
        filters({ altitudeMaxFt: 35000 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("keeps an aircraft inside the range", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", altitude_ft: 20000 })];
      const result = applyFilters(
        aircraft,
        filters({ altitudeMinFt: 10000, altitudeMaxFt: 30000 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });

    it("never excludes for unknown altitude — a range cannot compare what it does not have", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", altitude_ft: null })];
      const result = applyFilters(
        aircraft,
        filters({ altitudeMinFt: 10000, altitudeMaxFt: 30000 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("distance cap", () => {
    it("uses the config default when no override is set", () => {
      const aircraft = [
        makeAircraft({ icao: "near", distance_nm: 100 }),
        makeAircraft({ icao: "far", distance_nm: 300 }),
      ];
      const result = applyFilters(aircraft, DEFAULT_FILTERS, CONFIG);
      expect(result.visibleIcaos).toEqual(new Set(["near"]));
      expect(result.distanceCappedCount).toBe(1);
      expect(result.effectiveDistanceCapNm).toBe(250);
    });

    it("an explicit override replaces the default, tighter", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", distance_nm: 100 })];
      const result = applyFilters(
        aircraft,
        filters({ maxDistanceNm: 50 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
      expect(result.effectiveDistanceCapNm).toBe(50);
    });

    it("an explicit override replaces the default, wider", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", distance_nm: 300 })];
      const result = applyFilters(
        aircraft,
        filters({ maxDistanceNm: 400 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
      expect(result.effectiveDistanceCapNm).toBe(400);
    });

    it("never excludes for unknown distance", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", position: null, distance_nm: null }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ maxDistanceNm: 1 }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });

    it("stays in the store's own reported list — applyFilters only narrows the render set", () => {
      // The AC: capped aircraft remain in the store/APIs. This is a
      // property of how `applyFilters` is *used* (it's never fed back
      // into `useLiveAircraftStore`), but assert the input array is never
      // mutated as the closest thing a pure function can promise it.
      const aircraft = [makeAircraft({ icao: "far", distance_nm: 900 })];
      const snapshot = [...aircraft];
      applyFilters(aircraft, DEFAULT_FILTERS, CONFIG);
      expect(aircraft).toEqual(snapshot);
    });
  });

  describe("text matches (category/operator/operator group)", () => {
    it("matches a substring case-insensitively", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", aircraft_type: "Boeing 737-800" }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ categoryText: "737" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });

    it("excludes a null field rather than matching everything — the field simply is not '737' yet", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", aircraft_type: null })];
      const result = applyFilters(
        aircraft,
        filters({ categoryText: "737" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("filters on operator text", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", operator: "British Airways" }),
        makeAircraft({ icao: "bbbbbb", operator: "United" }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ operatorText: "british" }),
        CONFIG,
      );
      expect(result.visibleIcaos).toEqual(new Set(["aaaaaa"]));
    });

    it("filters on operator group text", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", operator_group: "Oneworld" }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ operatorGroupText: "star" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });
  });

  describe("classification", () => {
    it("selects nothing rather than everything when classification is null (today's live payload)", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", classification: null }),
        makeAircraft({ icao: "bbbbbb", classification: null }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ classifications: ["military"] }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("OR-matches selected flags once classification data exists", () => {
      const aircraft = [
        makeAircraft({
          icao: "aaaaaa",
          classification: {
            military: true,
            government: false,
            law_enforcement: false,
            mission: null,
            icon_category: null,
            confidence: null,
          },
        }),
        makeAircraft({
          icao: "bbbbbb",
          classification: {
            military: false,
            government: false,
            law_enforcement: false,
            mission: null,
            icon_category: null,
            confidence: null,
          },
        }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ classifications: ["military", "government"] }),
        CONFIG,
      );
      expect(result.visibleIcaos).toEqual(new Set(["aaaaaa"]));
    });
  });

  describe("mission category", () => {
    it("selects nothing when classification is null", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", classification: null })];
      const result = applyFilters(
        aircraft,
        filters({ missionCategories: ["medevac"] }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("matches classification.mission once populated", () => {
      const aircraft = [
        makeAircraft({
          icao: "aaaaaa",
          classification: {
            military: false,
            government: false,
            law_enforcement: false,
            mission: "medevac",
            icon_category: null,
            confidence: null,
          },
        }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ missionCategories: ["medevac"] }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("interesting-only", () => {
    it("excludes every aircraft while interesting is always null (today)", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", interesting: null })];
      const result = applyFilters(
        aircraft,
        filters({ interestingOnly: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("passes an aircraft with an active alert match", () => {
      const aircraft = [
        makeAircraft({
          icao: "aaaaaa",
          interesting: { severity: "high", reasons: ["test"] },
        }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ interestingOnly: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("emergency-only", () => {
    it("is real decoder data, not metadata-gated — excludes a non-emergency aircraft today", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", emergency: null })];
      const result = applyFilters(
        aircraft,
        filters({ emergencyOnly: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("passes an aircraft squawking an emergency code", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", emergency: "7700" })];
      const result = applyFilters(
        aircraft,
        filters({ emergencyOnly: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("hide non-positioned", () => {
    it("excludes an aircraft with no position", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", position: null, distance_nm: null }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ hideNonPositioned: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("keeps a positioned aircraft", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa" })];
      const result = applyFilters(
        aircraft,
        filters({ hideNonPositioned: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("ground traffic", () => {
    it("show: includes ground traffic undimmed", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", on_ground: true })];
      const result = applyFilters(
        aircraft,
        filters({ groundTraffic: "show" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
      expect(result.dimmedIcaos.size).toBe(0);
    });

    it("dim: includes ground traffic but flags it dimmed rather than excluding it", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", on_ground: true }),
        makeAircraft({ icao: "bbbbbb", on_ground: false }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ groundTraffic: "dim" }),
        CONFIG,
      );
      expect(result.visibleIcaos).toEqual(new Set(["aaaaaa", "bbbbbb"]));
      expect(result.dimmedIcaos).toEqual(new Set(["aaaaaa"]));
    });

    it("hide: excludes ground traffic entirely", () => {
      const aircraft = [
        makeAircraft({ icao: "aaaaaa", on_ground: true }),
        makeAircraft({ icao: "bbbbbb", on_ground: false }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ groundTraffic: "hide" }),
        CONFIG,
      );
      expect(result.visibleIcaos).toEqual(new Set(["bbbbbb"]));
    });

    it("never treats unknown on_ground as ground traffic", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", on_ground: null })];
      const result = applyFilters(
        aircraft,
        filters({ groundTraffic: "hide" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("staleness", () => {
    it("hideStale excludes a stale aircraft", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", state: "stale" })];
      const result = applyFilters(
        aircraft,
        filters({ hideStale: true }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("show-all (default) keeps a stale aircraft", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", state: "stale" })];
      const result = applyFilters(aircraft, DEFAULT_FILTERS, CONFIG);
      expect(result.aircraft).toHaveLength(1);
    });
  });

  describe("live-set query", () => {
    it("matches a callsign prefix, case-insensitively", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", callsign: "BAW123" })];
      const result = applyFilters(
        aircraft,
        filters({ liveSetQuery: "baw" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });

    it("matches a registration prefix", () => {
      const aircraft = [
        makeAircraft({
          icao: "aaaaaa",
          callsign: null,
          registration: "N12345",
        }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ liveSetQuery: "n123" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });

    it("matches an ICAO prefix", () => {
      const aircraft = [makeAircraft({ icao: "ae1463" })];
      const result = applyFilters(
        aircraft,
        filters({ liveSetQuery: "ae14" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(1);
    });

    it("is not a global search — a substring in the middle does not match", () => {
      const aircraft = [makeAircraft({ icao: "aaaaaa", callsign: "BAW123" })];
      const result = applyFilters(
        aircraft,
        filters({ liveSetQuery: "123" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });

    it("excludes an aircraft matching none of the three fields", () => {
      const aircraft = [
        makeAircraft({
          icao: "aaaaaa",
          callsign: "BAW123",
          registration: "G-TEST",
        }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ liveSetQuery: "zzz" }),
        CONFIG,
      );
      expect(result.aircraft).toHaveLength(0);
    });
  });

  describe("composition (AND across dimensions)", () => {
    it("requires every active filter to pass", () => {
      const aircraft = [
        makeAircraft({
          icao: "match",
          altitude_ft: 20000,
          distance_nm: 50,
          emergency: "7700",
          on_ground: false,
          state: "live",
        }),
        makeAircraft({
          icao: "fails-altitude",
          altitude_ft: 500,
          distance_nm: 50,
          emergency: "7700",
        }),
        makeAircraft({
          icao: "fails-emergency",
          altitude_ft: 20000,
          distance_nm: 50,
          emergency: null,
        }),
      ];
      const result = applyFilters(
        aircraft,
        filters({ altitudeMinFt: 10000, emergencyOnly: true }),
        CONFIG,
      );
      expect(result.visibleIcaos).toEqual(new Set(["match"]));
    });
  });

  describe("passesFilters", () => {
    it("agrees with applyFilters for a single aircraft", () => {
      const aircraft = makeAircraft({ icao: "aaaaaa", distance_nm: 300 });
      expect(passesFilters(aircraft, DEFAULT_FILTERS, CONFIG)).toBe(false);
      expect(
        applyFilters([aircraft], DEFAULT_FILTERS, CONFIG).aircraft,
      ).toHaveLength(0);
    });
  });
});
