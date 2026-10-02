import { describe, expect, it } from "vitest";

import {
  CATEGORY_ICON_SHAPES,
  EMITTER_CATEGORY_ICON_SHAPES,
  GENERIC_ICON_SHAPE,
  GROUND_ICON_SHAPE,
  resolveAircraftIcon,
  resolveAircraftIconImageId,
  resolveIconPalette,
  TYPE_ICON_SHAPES,
} from "@/features/map/aircraft/icons/resolveIcon";
import {
  AIRCRAFT_ICON_SHAPES,
  iconImageId,
} from "@/features/map/aircraft/icons/silhouettes";
import type { Classification } from "@/lib/api/live";

function classification(
  iconCategory: string | null,
  flags: Partial<Pick<Classification, "military" | "government" | "law_enforcement">> = {},
): Classification {
  return {
    military: false,
    government: false,
    law_enforcement: false,
    mission: null,
    icon_category: iconCategory,
    confidence: null,
    ...flags,
  };
}

describe("resolveAircraftIcon", () => {
  it("falls through to generic when no metadata is present", () => {
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

  it("ships populated tables whose every value is a drawn shape", () => {
    expect(Object.keys(TYPE_ICON_SHAPES).length).toBeGreaterThan(100);
    expect(Object.keys(CATEGORY_ICON_SHAPES).length).toBeGreaterThan(0);
    for (const table of [
      TYPE_ICON_SHAPES,
      CATEGORY_ICON_SHAPES,
      EMITTER_CATEGORY_ICON_SHAPES,
    ]) {
      for (const shape of Object.values(table)) {
        expect(AIRCRAFT_ICON_SHAPES).toContain(shape);
      }
    }
  });

  it("keys the type table by upper-case ICAO designators", () => {
    for (const code of Object.keys(TYPE_ICON_SHAPES)) {
      expect(code).toMatch(/^[A-Z0-9]{2,4}$/);
    }
  });

  it("prefers a type match over both the category and the ground variant", () => {
    expect(
      resolveAircraftIcon({
        aircraft_type: "b738",
        classification: classification("helicopter"),
        on_ground: true,
      }),
    ).toEqual({ shape: "narrowbody", level: "type" });
  });

  it("lets the type level correct a backend category the drawing disagrees with", () => {
    // The backend files a Chinook as a helicopter and an Osprey as military
    // transport; the type table knows better.
    expect(
      resolveAircraftIcon({
        aircraft_type: "H47",
        classification: classification("helicopter"),
        on_ground: false,
      }),
    ).toEqual({ shape: "tandem-rotor", level: "type" });
    expect(
      resolveAircraftIcon({
        aircraft_type: "V22",
        classification: classification("military_transport"),
        on_ground: false,
      }),
    ).toEqual({ shape: "tiltrotor", level: "type" });
  });

  describe("the type level, one designator per family", () => {
    it.each([
      ["C172", "light-high-wing"],
      ["SR22", "light-cirrus"],
      ["P28A", "light-low-wing"],
      ["BE58", "light-twin"],
      ["DH8D", "turboprop-twin"],
      ["GLF6", "business-jet"],
      ["A320", "narrowbody"],
      ["P8", "narrowbody"],
      ["B789", "widebody-twin"],
      ["B744", "widebody-quad"],
      ["A388", "widebody-quad"],
      ["F16", "fighter"],
      ["B52", "bomber"],
      ["K35R", "tanker"],
      ["C17", "military-transport"],
      ["P3", "patrol"],
      ["MQ9", "uav"],
      ["DISC", "glider"],
    ] as const)("%s draws %s", (designator, shape) => {
      expect(
        resolveAircraftIcon({
          aircraft_type: designator,
          classification: null,
          on_ground: false,
        }),
      ).toEqual({ shape, level: "type" });
    });

    it("lists no plain helicopter: the backend's rotorcraft table owns those", () => {
      for (const code of ["EC35", "H125", "B06", "R44", "S76", "AH64"]) {
        expect(TYPE_ICON_SHAPES[code]).toBeUndefined();
      }
    });
  });

  describe("the category level", () => {
    it.each([
      ["airliner", "narrowbody"],
      ["cargo", "narrowbody"],
      ["business_jet", "business-jet"],
      ["light_aircraft", "light-high-wing"],
      ["helicopter", "rotorcraft"],
      ["military_jet", "fighter"],
      ["military_transport", "military-transport"],
    ] as const)("%s draws %s", (category, shape) => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: classification(category),
          on_ground: false,
        }),
      ).toEqual({ shape, level: "category" });
    });

    it.each(["military", "government", "law_enforcement", "medical", "firefighting"])(
      "%s says who flies it, not what it is, so it falls through",
      (category) => {
        // A stated category outranks the transmitter even without a shape of
        // its own (module comment), so this is generic, not the emitter's A1.
        // The palette carries what the category was saying.
        expect(
          resolveAircraftIcon({
            aircraft_type: null,
            classification: classification(category),
            on_ground: false,
            emitter_category: "A1",
          }),
        ).toEqual({ shape: GENERIC_ICON_SHAPE, level: "generic" });
      },
    );
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

    it("never outranks a metadata category", () => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: classification("airliner"),
          on_ground: false,
          emitter_category: "A7",
        }),
      ).toEqual({ shape: "narrowbody", level: "category" });
    });

    it("never outranks a metadata type silhouette", () => {
      expect(
        resolveAircraftIcon({
          aircraft_type: "B738",
          classification: null,
          on_ground: false,
          emitter_category: "A7",
        }).level,
      ).toBe("type");
    });

    it.each([
      ["A1", "light-high-wing"],
      ["A2", "narrowbody"],
      ["A3", "narrowbody"],
      ["A4", "widebody-twin"],
      ["A5", "widebody-twin"],
      ["A6", "fighter"],
      ["A7", "rotorcraft"],
      ["B1", "glider"],
      ["B4", "glider"],
      ["B6", "uav"],
    ] as const)("%s draws %s", (code, shape) => {
      expect(
        resolveAircraftIcon({
          aircraft_type: null,
          classification: null,
          on_ground: false,
          emitter_category: code,
        }),
      ).toEqual({ shape, level: "emitter" });
    });

    it("falls through the categories with no silhouette of their own", () => {
      for (const code of ["A0", "B0", "B2", "B3", "B7", "C0", "C1", "C3", "D1"]) {
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

describe("resolveIconPalette", () => {
  it("is civil when nothing is known", () => {
    expect(resolveIconPalette(null)).toBe("civil");
    expect(resolveIconPalette(undefined)).toBe("civil");
    expect(resolveIconPalette(classification("airliner"))).toBe("civil");
  });

  it("is military for a military classification", () => {
    expect(resolveIconPalette(classification(null, { military: true }))).toBe(
      "military",
    );
  });

  it("is government for government or law-enforcement alone", () => {
    expect(resolveIconPalette(classification(null, { government: true }))).toBe(
      "government",
    );
    expect(
      resolveIconPalette(classification(null, { law_enforcement: true })),
    ).toBe("government");
  });

  it("lets military outrank government", () => {
    expect(
      resolveIconPalette(
        classification(null, { military: true, government: true }),
      ),
    ).toBe("military");
  });

  it("reads the flags, not the category or mission", () => {
    // `military_jet` without the flag is not a claim the palette may make.
    expect(resolveIconPalette(classification("military_jet"))).toBe("civil");
    expect(
      resolveIconPalette({ ...classification(null), mission: "military" }),
    ).toBe("civil");
  });
});

describe("resolveAircraftIconImageId", () => {
  it("composes the silhouette with the palette", () => {
    expect(
      resolveAircraftIconImageId({
        aircraft_type: "K35R",
        classification: classification("military_transport", { military: true }),
        on_ground: false,
      }),
    ).toBe(iconImageId("tanker", "military"));
    expect(
      resolveAircraftIconImageId({
        aircraft_type: "B738",
        classification: null,
        on_ground: false,
      }),
    ).toBe(iconImageId("narrowbody", "civil"));
    expect(
      resolveAircraftIconImageId({
        aircraft_type: null,
        classification: classification("helicopter", { law_enforcement: true }),
        on_ground: false,
      }),
    ).toBe(iconImageId("rotorcraft", "government"));
  });
});
