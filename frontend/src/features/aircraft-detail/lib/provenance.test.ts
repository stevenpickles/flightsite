import { describe, expect, it } from "vitest";

import {
  describeProvenance,
  fieldProvenance,
} from "@/features/aircraft-detail/lib/provenance";

describe("describeProvenance", () => {
  it.each([
    ["decoder", "Decoder"],
    ["derived", "Derived"],
    ["mictronics", "Mictronics"],
    ["faa", "FAA"],
    ["aerodatabox", "AeroDataBox"],
    ["vrs", "VRS standing data"],
    ["heuristic", "Heuristic"],
  ])("labels the documented source %s as %s", (source, label) => {
    const info = describeProvenance(source);
    expect(info.label).toBe(label);
    expect(info.description.length).toBeGreaterThan(0);
  });

  it("tells the two route sources apart (slice 071)", () => {
    // `provenance.route` now carries either the offline VRS directory or the
    // online provider, and the panel must not blur them into "route data".
    const vrs = describeProvenance("vrs");
    const aerodatabox = describeProvenance("aerodatabox");
    expect(vrs.label).not.toBe(aerodatabox.label);
    expect(vrs.description).toMatch(/Virtual Radar Server/);
    expect(aerodatabox.description).toMatch(/AeroDataBox/);
  });

  it("title-cases and describes an undocumented future source gracefully", () => {
    const info = describeProvenance("some_new_source");
    expect(info.source).toBe("some_new_source");
    expect(info.label).toBe("Some New Source");
    expect(info.description).toContain("Some New Source");
  });
});

describe("fieldProvenance", () => {
  it("defaults to decoder when the field has no map entry (§2.6)", () => {
    const info = fieldProvenance({ registration: "faa" }, "altitude_ft");
    expect(info.source).toBe("decoder");
  });

  it("resolves an entry present in the map", () => {
    const info = fieldProvenance({ distance_nm: "derived" }, "distance_nm");
    expect(info.source).toBe("derived");
    expect(info.label).toBe("Derived");
  });
});
