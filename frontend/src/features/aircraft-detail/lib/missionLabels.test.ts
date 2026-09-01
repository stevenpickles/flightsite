import { describe, expect, it } from "vitest";

import {
  MISSION_LABELS,
  missionLabel,
} from "@/features/aircraft-detail/lib/missionLabels";

// SPEC §39's full enum, spelled as `flightsite.classification.vocabulary.MissionCategory`.
const DOCUMENTED_VALUES = [
  "commercial_passenger",
  "cargo",
  "general_aviation",
  "business_aviation",
  "military",
  "government",
  "law_enforcement",
  "medical",
  "firefighting",
  "training",
  "helicopter",
  "unknown",
] as const;

describe("MISSION_LABELS", () => {
  it("covers every SPEC §39 mission category with a human label", () => {
    for (const value of DOCUMENTED_VALUES) {
      expect(MISSION_LABELS[value]).toBeTypeOf("string");
      expect(MISSION_LABELS[value]?.length).toBeGreaterThan(0);
      // Never just the raw slug re-spelled with underscores.
      expect(MISSION_LABELS[value]).not.toContain("_");
    }
  });

  it("spells the documented values as readable prose", () => {
    expect(MISSION_LABELS.commercial_passenger).toBe("Commercial passenger");
    expect(MISSION_LABELS.cargo).toBe("Cargo");
    expect(MISSION_LABELS.general_aviation).toBe("General aviation");
    expect(MISSION_LABELS.business_aviation).toBe("Business aviation");
    expect(MISSION_LABELS.military).toBe("Military");
    expect(MISSION_LABELS.government).toBe("Government");
    expect(MISSION_LABELS.law_enforcement).toBe("Law enforcement");
    expect(MISSION_LABELS.medical).toBe("Medical / air ambulance");
    expect(MISSION_LABELS.firefighting).toBe("Firefighting");
    expect(MISSION_LABELS.training).toBe("Training");
    expect(MISSION_LABELS.helicopter).toBe("Helicopter");
    expect(MISSION_LABELS.unknown).toBe("Unknown");
  });
});

describe("missionLabel", () => {
  it.each(DOCUMENTED_VALUES)("labels %s from the map", (value) => {
    expect(missionLabel(value)).toBe(MISSION_LABELS[value]);
  });

  it("falls back to Unknown for null", () => {
    expect(missionLabel(null)).toBe("Unknown");
  });

  it("title-cases an undocumented value instead of showing nothing", () => {
    expect(missionLabel("some_new_mission")).toBe("Some New Mission");
  });
});
