import { afterEach, describe, expect, it, vi } from "vitest";

import {
  detectBrowserTimezone,
  listTimezones,
} from "@/features/setup/lib/timezones";

const originalSupportedValuesOf = Intl.supportedValuesOf;
const originalDateTimeFormat = Intl.DateTimeFormat;

afterEach(() => {
  Intl.supportedValuesOf = originalSupportedValuesOf;
  Intl.DateTimeFormat = originalDateTimeFormat;
  vi.restoreAllMocks();
});

describe("listTimezones", () => {
  it("returns a non-empty list of IANA zones when Intl.supportedValuesOf is available", () => {
    const zones = listTimezones();
    expect(zones.length).toBeGreaterThan(0);
    expect(zones).toContain("Europe/London");
  });

  it("falls back to the curated list when Intl.supportedValuesOf is unavailable", () => {
    // @ts-expect-error -- deliberately simulating an older runtime.
    Intl.supportedValuesOf = undefined;
    const zones = listTimezones();
    expect(zones).toContain("UTC");
    expect(zones).toContain("Europe/London");
  });

  it("falls back to the curated list when Intl.supportedValuesOf throws", () => {
    Intl.supportedValuesOf = () => {
      throw new Error("not supported");
    };
    const zones = listTimezones();
    expect(zones).toContain("UTC");
  });
});

describe("detectBrowserTimezone", () => {
  it("returns the runtime's resolved timezone", () => {
    expect(typeof detectBrowserTimezone()).toBe("string");
    expect(detectBrowserTimezone().length).toBeGreaterThan(0);
  });

  it("falls back to UTC when Intl.DateTimeFormat throws", () => {
    // @ts-expect-error -- deliberately simulating a broken Intl implementation.
    Intl.DateTimeFormat = () => {
      throw new Error("broken");
    };
    expect(detectBrowserTimezone()).toBe("UTC");
  });
});
