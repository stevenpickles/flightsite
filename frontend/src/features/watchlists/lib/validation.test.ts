import { describe, expect, it } from "vitest";

import {
  MAX_DESCRIPTION_LENGTH,
  MAX_NAME_LENGTH,
  MAX_NOTE_LENGTH,
  MAX_VALUE_LENGTH,
  validateEntryNote,
  validateEntryValue,
  validateWatchlistDescription,
  validateWatchlistName,
} from "@/features/watchlists/lib/validation";

describe("validateWatchlistName", () => {
  it("rejects a blank name", () => {
    expect(validateWatchlistName("   ")).not.toBeNull();
  });

  it("rejects a name over the length limit", () => {
    expect(
      validateWatchlistName("x".repeat(MAX_NAME_LENGTH + 1)),
    ).not.toBeNull();
  });

  it("accepts a trimmed, in-bounds name", () => {
    expect(validateWatchlistName("  Local Police  ")).toBeNull();
  });
});

describe("validateWatchlistDescription", () => {
  it("accepts a blank description", () => {
    expect(validateWatchlistDescription("")).toBeNull();
  });

  it("rejects a description over the length limit", () => {
    expect(
      validateWatchlistDescription("x".repeat(MAX_DESCRIPTION_LENGTH + 1)),
    ).not.toBeNull();
  });
});

describe("validateEntryNote", () => {
  it("accepts a blank note", () => {
    expect(validateEntryNote("")).toBeNull();
  });

  it("rejects a note over the length limit", () => {
    expect(validateEntryNote("x".repeat(MAX_NOTE_LENGTH + 1))).not.toBeNull();
  });
});

describe("validateEntryValue", () => {
  it("requires a value for every kind", () => {
    for (const kind of [
      "icao24",
      "registration",
      "type_code",
      "operator",
      "category",
    ] as const) {
      expect(validateEntryValue(kind, "   ")).not.toBeNull();
    }
  });

  it("rejects a value over the length limit", () => {
    expect(
      validateEntryValue("operator", "x".repeat(MAX_VALUE_LENGTH + 1)),
    ).not.toBeNull();
  });

  describe("icao24", () => {
    it("accepts exactly six hex digits", () => {
      expect(validateEntryValue("icao24", "ae1463")).toBeNull();
      expect(validateEntryValue("icao24", "AE1463")).toBeNull();
    });

    it("rejects the wrong length or non-hex characters", () => {
      expect(validateEntryValue("icao24", "ae146")).not.toBeNull();
      expect(validateEntryValue("icao24", "ae14633")).not.toBeNull();
      expect(validateEntryValue("icao24", "zzzzzz")).not.toBeNull();
    });
  });

  describe("registration", () => {
    it("accepts a plausible tail number", () => {
      expect(validateEntryValue("registration", "N12345")).toBeNull();
      expect(validateEntryValue("registration", "G-ABCD")).toBeNull();
    });

    it("rejects a value starting or ending with a hyphen", () => {
      expect(validateEntryValue("registration", "-ABC")).not.toBeNull();
      expect(validateEntryValue("registration", "ABC-")).not.toBeNull();
    });
  });

  describe("type_code", () => {
    it("accepts a 2-6 character alphanumeric designator", () => {
      expect(validateEntryValue("type_code", "B738")).toBeNull();
      expect(validateEntryValue("type_code", "EC")).toBeNull();
    });

    it("rejects a single character or an over-long designator", () => {
      expect(validateEntryValue("type_code", "B")).not.toBeNull();
      expect(validateEntryValue("type_code", "TOOLONGCODE")).not.toBeNull();
    });
  });

  describe("operator", () => {
    it("accepts any non-blank text within the length limit", () => {
      expect(validateEntryValue("operator", "Delta Air Lines")).toBeNull();
    });
  });

  describe("category", () => {
    it("accepts a known category", () => {
      expect(validateEntryValue("category", "military")).toBeNull();
    });

    it("rejects an unknown category", () => {
      expect(validateEntryValue("category", "spaceship")).not.toBeNull();
    });

    it("rejects 'unknown' itself", () => {
      expect(validateEntryValue("category", "unknown")).not.toBeNull();
    });
  });
});
