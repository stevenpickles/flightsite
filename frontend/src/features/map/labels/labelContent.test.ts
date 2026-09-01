import { describe, expect, it } from "vitest";

import {
  buildAircraftLabelLines,
  buildIdentityLine,
  buildOperatorLine,
  formatAltitude,
  INTERESTING_INDICATOR,
  renderLabelText,
  TRANSITION_ALTITUDE_FT,
  type LabelSourceAircraft,
} from "@/features/map/labels/labelContent";

function aircraft(
  overrides: Partial<LabelSourceAircraft> = {},
): LabelSourceAircraft {
  return {
    icao: "ae1463",
    callsign: "RCH471",
    registration: null,
    operator: null,
    altitude_ft: 31000,
    interesting: null,
    ...overrides,
  };
}

describe("buildIdentityLine", () => {
  it("uses the callsign when present", () => {
    expect(buildIdentityLine(aircraft({ callsign: "RCH471" }))).toBe("RCH471");
  });

  it("falls back to registration when the callsign is null", () => {
    expect(
      buildIdentityLine(aircraft({ callsign: null, registration: "N12345" })),
    ).toBe("N12345");
  });

  it("falls back to the upper-cased ICAO when both are null", () => {
    expect(
      buildIdentityLine(
        aircraft({ icao: "ae1463", callsign: null, registration: null }),
      ),
    ).toBe("AE1463");
  });

  it("treats a whitespace-only callsign as absent", () => {
    expect(
      buildIdentityLine(aircraft({ callsign: "   ", registration: "N12345" })),
    ).toBe("N12345");
  });

  it("prefixes the interesting indicator when the aircraft has an active match", () => {
    expect(
      buildIdentityLine(
        aircraft({
          callsign: "RCH471",
          interesting: { severity: "high", reasons: ["test"] },
        }),
      ),
    ).toBe(`${INTERESTING_INDICATOR} RCH471`);
  });

  it("omits the indicator while interesting is null", () => {
    expect(
      buildIdentityLine(aircraft({ callsign: "RCH471", interesting: null })),
    ).not.toContain(INTERESTING_INDICATOR);
  });
});

describe("buildOperatorLine", () => {
  it("is null while the metadata field is null", () => {
    expect(buildOperatorLine(aircraft({ operator: null }))).toBeNull();
  });

  it("renders the operator once the field carries a value", () => {
    expect(buildOperatorLine(aircraft({ operator: "Republic Airlines" }))).toBe(
      "Republic Airlines",
    );
  });

  it("treats a whitespace-only operator as absent", () => {
    expect(buildOperatorLine(aircraft({ operator: "   " }))).toBeNull();
  });
});

describe("formatAltitude", () => {
  it("is null when altitude is unknown", () => {
    expect(formatAltitude(null)).toBeNull();
  });

  it("formats feet with a thousands separator below the transition altitude", () => {
    expect(formatAltitude(3200)).toBe("3,200 ft");
    expect(formatAltitude(TRANSITION_ALTITUDE_FT - 1)).toBe("17,999 ft");
  });

  it("switches to flight-level notation at and above the transition altitude", () => {
    expect(formatAltitude(TRANSITION_ALTITUDE_FT)).toBe("FL180");
    expect(formatAltitude(35000)).toBe("FL350");
  });

  it("rounds to the nearest hundred feet for flight levels", () => {
    expect(formatAltitude(35050)).toBe("FL351");
  });
});

describe("buildAircraftLabelLines", () => {
  it("composes all three lines from one aircraft", () => {
    expect(
      buildAircraftLabelLines(
        aircraft({
          callsign: "RCH471",
          operator: "Republic Airlines",
          altitude_ft: 35000,
        }),
      ),
    ).toEqual({
      line1: "RCH471",
      line2: "Republic Airlines",
      line3: "FL350",
    });
  });

  it("leaves line 2 and line 3 null when their data is unavailable", () => {
    expect(
      buildAircraftLabelLines(
        aircraft({ callsign: "RCH471", operator: null, altitude_ft: null }),
      ),
    ).toEqual({ line1: "RCH471", line2: null, line3: null });
  });
});

describe("renderLabelText", () => {
  const lines = { line1: "RCH471", line2: "Republic Airlines", line3: "FL350" };

  it("is empty for the none tier", () => {
    expect(renderLabelText(lines, "none")).toBe("");
  });

  it("keeps only line 1 for the callsign tier", () => {
    expect(renderLabelText(lines, "callsign")).toBe("RCH471");
  });

  it("joins every available line for the full tier", () => {
    expect(renderLabelText(lines, "full")).toBe(
      "RCH471\nRepublic Airlines\nFL350",
    );
  });

  it("skips null lines rather than rendering a blank line", () => {
    expect(
      renderLabelText({ line1: "RCH471", line2: null, line3: "FL350" }, "full"),
    ).toBe("RCH471\nFL350");
    expect(
      renderLabelText({ line1: "RCH471", line2: null, line3: null }, "full"),
    ).toBe("RCH471");
  });
});
