import { describe, expect, it } from "vitest";

import {
  parseNumber,
  validateAntennaHeight,
  validateHost,
  validateLatitude,
  validateLongitude,
  validatePath,
  validatePollInterval,
  validatePort,
  validateSiteName,
} from "@/features/setup/lib/validation";

describe("parseNumber", () => {
  it("parses a valid numeric string", () => {
    expect(parseNumber("47.6")).toBe(47.6);
    expect(parseNumber("-122")).toBe(-122);
  });

  it("returns null for blank or non-numeric input", () => {
    expect(parseNumber("")).toBeNull();
    expect(parseNumber("   ")).toBeNull();
    expect(parseNumber("abc")).toBeNull();
  });
});

describe("validateSiteName", () => {
  it("requires a non-blank name", () => {
    expect(validateSiteName("")).toMatch(/required/i);
    expect(validateSiteName("   ")).toMatch(/required/i);
  });

  it("accepts a name within the length limit", () => {
    expect(validateSiteName("Home Roof Antenna")).toBeNull();
  });

  it("rejects a name over 120 characters", () => {
    expect(validateSiteName("a".repeat(121))).toMatch(/120/);
  });
});

describe("validateLatitude", () => {
  it.each([-90, 0, 47.6, 90])("accepts %s", (value) => {
    expect(validateLatitude(String(value))).toBeNull();
  });

  it.each(["-90.1", "90.1", "", "abc"])("rejects %s", (value) => {
    expect(validateLatitude(value)).not.toBeNull();
  });
});

describe("validateLongitude", () => {
  it.each([-180, 0, -122.3, 180])("accepts %s", (value) => {
    expect(validateLongitude(String(value))).toBeNull();
  });

  it.each(["-180.1", "180.1", "", "abc"])("rejects %s", (value) => {
    expect(validateLongitude(value)).not.toBeNull();
  });
});

describe("validateAntennaHeight", () => {
  it("is optional — blank is valid", () => {
    expect(validateAntennaHeight("")).toBeNull();
  });

  it("accepts a value within range", () => {
    expect(validateAntennaHeight("30")).toBeNull();
  });

  it("rejects an out-of-range value", () => {
    expect(validateAntennaHeight("30001")).not.toBeNull();
    expect(validateAntennaHeight("-1401")).not.toBeNull();
  });
});

describe("validateHost", () => {
  it("requires a non-blank host", () => {
    expect(validateHost("")).not.toBeNull();
    expect(validateHost("127.0.0.1")).toBeNull();
  });
});

describe("validatePort", () => {
  it("accepts a port in range", () => {
    expect(validatePort("8080")).toBeNull();
    expect(validatePort("1")).toBeNull();
    expect(validatePort("65535")).toBeNull();
  });

  it("rejects out-of-range or non-integer ports", () => {
    expect(validatePort("0")).not.toBeNull();
    expect(validatePort("65536")).not.toBeNull();
    expect(validatePort("8080.5")).not.toBeNull();
    expect(validatePort("")).not.toBeNull();
  });
});

describe("validatePath", () => {
  it("requires a leading slash", () => {
    expect(validatePath("data/aircraft.json")).toMatch(/must start with/i);
  });

  it("accepts a well-formed path", () => {
    expect(validatePath("/data/aircraft.json")).toBeNull();
  });
});

describe("validatePollInterval", () => {
  it("accepts a value in (0, 60]", () => {
    expect(validatePollInterval("1")).toBeNull();
    expect(validatePollInterval("60")).toBeNull();
  });

  it("rejects zero, negative, or over-60 values", () => {
    expect(validatePollInterval("0")).not.toBeNull();
    expect(validatePollInterval("-1")).not.toBeNull();
    expect(validatePollInterval("60.1")).not.toBeNull();
  });
});
