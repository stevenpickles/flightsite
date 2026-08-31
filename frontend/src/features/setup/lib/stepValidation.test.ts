import { describe, expect, it } from "vitest";

import { isStepValid } from "@/features/setup/lib/stepValidation";
import { draftFromConfig } from "@/features/setup/lib/draft";
import {
  INITIAL_DECODER_TEST_STATE,
  type DecoderTestState,
} from "@/features/setup/types";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

const validDraft = draftFromConfig({
  first_run: true,
  config: defaultFlightSiteConfig({
    location: {
      latitude: 47.6,
      longitude: -122.3,
      site_name: "Home",
      antenna_height_ft: null,
    },
  }),
  secrets_set: { "enrichment.aerodatabox_api_key": false },
});

describe("isStepValid", () => {
  it("welcome requires a non-blank site name", () => {
    expect(isStepValid("welcome", validDraft, INITIAL_DECODER_TEST_STATE)).toBe(
      true,
    );
    expect(
      isStepValid(
        "welcome",
        { ...validDraft, siteName: "" },
        INITIAL_DECODER_TEST_STATE,
      ),
    ).toBe(false);
  });

  it("location requires valid latitude/longitude", () => {
    expect(
      isStepValid("location", validDraft, INITIAL_DECODER_TEST_STATE),
    ).toBe(true);
    expect(
      isStepValid(
        "location",
        { ...validDraft, latitude: "" },
        INITIAL_DECODER_TEST_STATE,
      ),
    ).toBe(false);
    expect(
      isStepValid(
        "location",
        { ...validDraft, longitude: "200" },
        INITIAL_DECODER_TEST_STATE,
      ),
    ).toBe(false);
  });

  it("decoder requires valid fields and a passed-or-skipped test", () => {
    expect(isStepValid("decoder", validDraft, INITIAL_DECODER_TEST_STATE)).toBe(
      false,
    );

    const passed: DecoderTestState = {
      status: "success",
      skipped: false,
      message: "ok",
    };
    expect(isStepValid("decoder", validDraft, passed)).toBe(true);

    const skipped: DecoderTestState = {
      status: "idle",
      skipped: true,
      message: null,
    };
    expect(isStepValid("decoder", validDraft, skipped)).toBe(true);

    const invalidFields = { ...validDraft, receiverPort: "0" };
    expect(isStepValid("decoder", invalidFields, passed)).toBe(false);
  });

  it("units-timezone requires a non-blank timezone", () => {
    expect(
      isStepValid("units-timezone", validDraft, INITIAL_DECODER_TEST_STATE),
    ).toBe(true);
    expect(
      isStepValid(
        "units-timezone",
        { ...validDraft, timezone: "" },
        INITIAL_DECODER_TEST_STATE,
      ),
    ).toBe(false);
  });

  it.each(["notifications", "metadata", "alerts", "review"] as const)(
    "%s is always valid",
    (stepId) => {
      expect(isStepValid(stepId, validDraft, INITIAL_DECODER_TEST_STATE)).toBe(
        true,
      );
    },
  );
});
