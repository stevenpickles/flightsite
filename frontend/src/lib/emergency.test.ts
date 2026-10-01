import { describe, expect, it } from "vitest";

import {
  EMERGENCY_KIND_LABELS,
  decoderEmergencyAddsToSquawk,
  emergencyHeadline,
  emergencyKindLabel,
} from "@/lib/emergency";

describe("decoderEmergencyAddsToSquawk", () => {
  it("adds a decoder emergency to an ordinary squawk", () => {
    expect(decoderEmergencyAddsToSquawk("nordo", "2341")).toBe(true);
    expect(decoderEmergencyAddsToSquawk("minfuel", null)).toBe(true);
  });

  it("adds nothing when the squawk already declares the same kind", () => {
    expect(decoderEmergencyAddsToSquawk("nordo", "7600")).toBe(false);
    expect(decoderEmergencyAddsToSquawk("general", "7700")).toBe(false);
    expect(decoderEmergencyAddsToSquawk("unlawful", "7500")).toBe(false);
  });

  it("adds a different kind from the squawk's", () => {
    expect(decoderEmergencyAddsToSquawk("minfuel", "7700")).toBe(true);
  });

  it("adds nothing when the decoder declares nothing", () => {
    expect(decoderEmergencyAddsToSquawk(null, "7700")).toBe(false);
    expect(decoderEmergencyAddsToSquawk(undefined, "2341")).toBe(false);
  });
});

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
