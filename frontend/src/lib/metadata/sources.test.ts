import { describe, expect, it } from "vitest";

import { rowNoun, sourceLabel } from "@/lib/metadata/sources";

describe("sourceLabel", () => {
  it("names the listed sources by their proper display name", () => {
    expect(sourceLabel("mictronics")).toBe("Mictronics");
    expect(sourceLabel("faa")).toBe("FAA");
    expect(sourceLabel("opensky")).toBe("OpenSky");
    expect(sourceLabel("routes")).toBe("Flight routes (VRS)");
    expect(sourceLabel("demo")).toBe("Demo");
  });

  it("capitalizes an unlisted source rather than throwing (R4-14)", () => {
    // `airports` is deliberately unlisted — capitalizing it already reads
    // correctly — and a future source this list has not caught up with
    // yet must still render something, not an error.
    expect(sourceLabel("airports")).toBe("Airports");
    expect(sourceLabel("future_source")).toBe("Future_source");
  });
});

describe("rowNoun", () => {
  it("names airports and routes rows by what they are", () => {
    expect(rowNoun("airports")).toBe("airports");
    expect(rowNoun("routes")).toBe("routes");
  });

  it("defaults to 'aircraft' for every airframe source", () => {
    expect(rowNoun("mictronics")).toBe("aircraft");
    expect(rowNoun("faa")).toBe("aircraft");
    expect(rowNoun("opensky")).toBe("aircraft");
    expect(rowNoun("demo")).toBe("aircraft");
  });
});
