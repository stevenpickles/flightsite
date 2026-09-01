import { describe, expect, it } from "vitest";

import { classificationSummary } from "@/features/aircraft-detail/lib/classificationSummary";
import type { Classification } from "@/lib/api/live";

function classification(
  overrides: Partial<Classification> = {},
): Classification {
  return {
    military: false,
    government: false,
    law_enforcement: false,
    mission: "unknown",
    icon_category: null,
    confidence: null,
    ...overrides,
  };
}

describe("classificationSummary", () => {
  it("returns null for a null classification (§2.7 unknown)", () => {
    expect(classificationSummary(null)).toBeNull();
  });

  it("renders the mission label using MISSION_LABELS, not the raw slug", () => {
    expect(
      classificationSummary(
        classification({ mission: "military", military: true }),
      ),
    ).toBe("Military · Military");
  });

  it("joins every set flag", () => {
    expect(
      classificationSummary(
        classification({
          government: true,
          law_enforcement: true,
          mission: "government",
        }),
      ),
    ).toBe("Government, Law enforcement · Government");
  });

  it("reads 'Civilian' when no flag is set", () => {
    expect(
      classificationSummary(
        classification({ mission: "commercial_passenger" }),
      ),
    ).toBe("Civilian · Commercial passenger");
  });
});
