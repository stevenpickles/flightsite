import { afterEach, describe, expect, it } from "vitest";

import {
  CATEGORY_ICON_SHAPES,
  EMITTER_CATEGORY_ICON_SHAPES,
  GENERIC_ICON_SHAPE,
  GROUND_ICON_SHAPE,
  resolveAircraftIcon,
  TYPE_ICON_SHAPES,
} from "@/features/map/aircraft/icons/resolveIcon";
import type { AircraftIconShape } from "@/features/map/aircraft/icons/silhouettes";
import type { Classification } from "@/lib/api/live";

/** The shipped type table is empty until slice 024. Writing through this alias
 * is how the type level of the hierarchy is exercised today; every test that
 * does so clears its entry again. */
const typeTable = TYPE_ICON_SHAPES as Record<string, AircraftIconShape>;

afterEach(() => {
  for (const key of Object.keys(typeTable)) {
    delete typeTable[key];
  }
});

function classification(iconCategory: string | null): Classification {
  return {
    military: false,
    government: false,
    law_enforcement: false,
    mission: null,
    icon_category: iconCategory,
    confidence: null,
  };
}

describe("resolveAircraftIcon", () => {
  it("falls through to generic when no metadata is present", () => {
    // The state of every live payload until slices 021-024 land: the metadata
    // half of the §3.3 object is present and null.
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: null,
        on_ground: false,
      }),
    ).toEqual({ shape: GENERIC_ICON_SHAPE, level: "generic" });
  });

  it("uses the ground variant for an aircraft the decoder reports on the ground", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: null,
        on_ground: true,
      }),
    ).toEqual({ shape: GROUND_ICON_SHAPE, level: "generic" });
  });

  it("treats an unknown ground state as airborne", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: null,
        on_ground: null,
      }).shape,
    ).toBe(GENERIC_ICON_SHAPE);
  });

  it("prefers a category match over the generic fallback", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: classification("helicopter"),
        on_ground: false,
      }),
    ).toEqual({ shape: "rotorcraft", level: "category" });
  });

  it("matches categories case- and whitespace-insensitively", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: classification("  Rotorcraft "),
        on_ground: false,
      }).level,
    ).toBe("category");
  });

  it("keeps a category silhouette while the aircraft is on the ground", () => {
    // The ground variant is the *generic* fallback's ground form, not a level
    // of the hierarchy: real metadata outranks the decoder's ground flag.
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: classification("helicopter"),
        on_ground: true,
      }),
    ).toEqual({ shape: "rotorcraft", level: "category" });
  });

  it("falls through an unrecognised category", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: classification("balloon"),
        on_ground: false,
      }).level,
    ).toBe("generic");
  });

  it("falls through an empty category string", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: "  ",
        classification: classification("   "),
        on_ground: false,
      }).level,
    ).toBe("generic");
  });

  it("ships an empty type table and a populated category table", () => {
    // The plumbing is what slice 014 owns; slice 024 supplies the type data.
    expect(TYPE_ICON_SHAPES).toEqual({});
    expect(Object.keys(CATEGORY_ICON_SHAPES).length).toBeGreaterThan(0);
  });

  it("prefers a type match over both the category and the ground variant", () => {
    // Simulates slice 024 populating the table: activating type-specific
    // silhouettes must be filling this in, not changing the resolver.
    typeTable.B738 = "airliner";
    expect(
      resolveAircraftIcon({
        aircraft_type: "b738",
        classification: classification("helicopter"),
        on_ground: true,
      }),
    ).toEqual({ shape: "airliner", level: "type" });
  });

  describe("emitter-category fallback (roadmap slice 086)", () => {
    it("renders an A7 with no metadata as a rotorcraft", () => {
      // The roadmap acceptance criterion.
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: null,
          on_ground: false,
          emitter_category: "A7",
        }),
      ).toEqual({ shape: "rotorcraft", level: "emitter" });
    });

    it("keeps the rotorcraft on the ground", () => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: null,
          on_ground: true,
          emitter_category: "A7",
        }),
      ).toEqual({ shape: "rotorcraft", level: "emitter" });
    });

    it("applies when metadata resolved but its category is unknown", () => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: classification("unknown"),
          on_ground: false,
          emitter_category: "a7",
        }).level,
      ).toBe("emitter");
    });

    it("never outranks a metadata category, even a generic-shaped one", () => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: classification("airliner"),
          on_ground: false,
          emitter_category: "A7",
        }),
      ).toEqual({ shape: GENERIC_ICON_SHAPE, level: "generic" });
    });

    it("never outranks a metadata type silhouette", () => {
      typeTable.B738 = "airliner";
      expect(
        resolveAircraftIcon({
          aircraft_type: "B738",
          classification: null,
          on_ground: false,
          emitter_category: "A7",
        }).level,
      ).toBe("type");
    });

    it("maps only shapes that exist, so other categories fall through", () => {
      expect(EMITTER_CATEGORY_ICON_SHAPES).toEqual({ A7: "rotorcraft" });
      for (const code of ["A0", "A1", "A3", "A5", "A6", "B1", "B6", "C1"]) {
        expect(
          resolveAircraftIcon({
            aircraft_type: null,
            classification: null,
            on_ground: false,
            emitter_category: code,
          }),
        ).toEqual({ shape: GENERIC_ICON_SHAPE, level: "generic" });
      }
    });

    it("ignores a malformed category", () => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: null,
          on_ground: false,
          emitter_category: "constructor",
        }).level,
      ).toBe("generic");
    });
  });

  it("makes no heuristic guess from live kinematics", () => {
    // A slow, low aircraft is not evidence of a rotorcraft: SPEC §39 requires
    // classification to carry provenance rather than claim certainty on weak
    // evidence, so it renders generic until metadata says otherwise.
    expect(
      resolveAircraftIcon({
        aircraft_type: null,
        classification: classification(null),
        on_ground: false,
      }),
    ).toEqual({ shape: GENERIC_ICON_SHAPE, level: "generic" });
  });
});
