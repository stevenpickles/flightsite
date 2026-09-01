import { describe, expect, it } from "vitest";

import {
  DEFAULT_PRESET,
  parseAnalyticsPreset,
  serializeAnalyticsPreset,
} from "@/features/analytics/lib/urlState";

describe("parseAnalyticsPreset", () => {
  it("defaults to today when the param is absent", () => {
    expect(parseAnalyticsPreset(new URLSearchParams())).toBe("today");
  });

  it("reads a valid preset", () => {
    expect(parseAnalyticsPreset(new URLSearchParams("preset=7d"))).toBe("7d");
    expect(parseAnalyticsPreset(new URLSearchParams("preset=t0"))).toBe("t0");
  });

  it("defaults on a malformed value rather than throwing", () => {
    expect(parseAnalyticsPreset(new URLSearchParams("preset=bogus"))).toBe(
      "today",
    );
  });
});

describe("serializeAnalyticsPreset", () => {
  it("omits the param for the default preset", () => {
    expect(serializeAnalyticsPreset(DEFAULT_PRESET).toString()).toBe("");
  });

  it("writes the param for a non-default preset", () => {
    expect(serializeAnalyticsPreset("30d").toString()).toBe("preset=30d");
  });

  it("round-trips every preset through parse -> serialize -> parse", () => {
    const presets: (typeof DEFAULT_PRESET | "7d" | "30d" | "ytd" | "t0")[] = [
      "today",
      "7d",
      "30d",
      "ytd",
      "t0",
    ];
    for (const preset of presets) {
      const params = serializeAnalyticsPreset(preset);
      expect(parseAnalyticsPreset(params)).toBe(preset);
    }
  });
});
