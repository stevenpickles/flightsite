import { describe, expect, it } from "vitest";

import {
  EMERGENCY_KIND_LABELS,
  emergencyHeadline,
  emergencyKindLabel,
} from "@/lib/emergency";

describe("emergencyKindLabel", () => {
  it("names every kind in plain words", () => {
    expect(EMERGENCY_KIND_LABELS).toEqual({
      general: "General emergency",
      lifeguard: "Lifeguard / medical",
      minfuel: "Minimum fuel",
      nordo: "No radio",
      unlawful: "Unlawful interference",
      downed: "Downed",
    });
  });

  it("is null for an absent or unknown kind rather than a raw slug", () => {
    expect(emergencyKindLabel(null)).toBeNull();
    expect(emergencyKindLabel(undefined)).toBeNull();
    expect(emergencyKindLabel("mayday")).toBeNull();
    // Not fooled by inherited properties.
    expect(emergencyKindLabel("toString")).toBeNull();
  });
});

describe("emergencyHeadline", () => {
  it("leads a decoder-declared emergency with its kind", () => {
    expect(emergencyHeadline(null, "decoder", "minfuel")).toBe(
      "Emergency: Minimum fuel",
    );
    // An ordinary squawk beside a decoder source is not the emergency.
    expect(emergencyHeadline("2341", "decoder", "nordo")).toBe(
      "Emergency: No radio",
    );
  });

  it("leads a squawk-declared emergency with its code, then the kind", () => {
    expect(emergencyHeadline("7500", "squawk", "unlawful")).toBe(
      "Emergency squawk 7500 · Unlawful interference",
    );
  });

  it("reads a payload from before slice 086 exactly as it used to", () => {
    expect(emergencyHeadline("7700", null, null)).toBe("Emergency squawk 7700");
    expect(emergencyHeadline(null, null, null)).toBe("Emergency squawk");
  });
});
