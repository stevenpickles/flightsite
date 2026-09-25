import { afterEach, describe, expect, it } from "vitest";

import {
  clearWizardSession,
  loadWizardSession,
  saveWizardSession,
  WIZARD_SESSION_STORAGE_KEY,
} from "@/features/setup/lib/sessionDraft";
import type { WizardDraft } from "@/features/setup/types";

const DRAFT: WizardDraft = {
  siteName: "R4 Review Site",
  latitude: "47.6",
  longitude: "-122.3",
  antennaHeightFt: "",
  receiverHost: "127.0.0.1",
  receiverPort: "8080",
  receiverPath: "/data/aircraft.json",
  pollIntervalS: "1",
  units: "aviation",
  timezone: "UTC",
  notifications: {
    enabled: true,
    info: false,
    interesting: true,
    high: true,
    critical: true,
  },
  aerodataboxKeyInput: "",
  aerodataboxKeyTouched: false,
  aerodataboxEnabled: false,
  enabledTemplateIds: [],
};

afterEach(() => {
  window.sessionStorage.clear();
});

describe("loadWizardSession / saveWizardSession", () => {
  it("round-trips a saved session", () => {
    saveWizardSession(DRAFT, 2, 3);

    expect(loadWizardSession()).toEqual({
      draft: DRAFT,
      stepIndex: 2,
      furthestStepIndex: 3,
    });
  });

  it("returns null when nothing has been saved", () => {
    expect(loadWizardSession()).toBeNull();
  });

  it("returns null for malformed JSON rather than throwing", () => {
    window.sessionStorage.setItem(WIZARD_SESSION_STORAGE_KEY, "{not json");
    expect(loadWizardSession()).toBeNull();
  });

  it("returns null for a value that is not a wizard session (wrong shape)", () => {
    window.sessionStorage.setItem(
      WIZARD_SESSION_STORAGE_KEY,
      JSON.stringify({ draft: DRAFT }), // missing stepIndex/furthestStepIndex
    );
    expect(loadWizardSession()).toBeNull();

    window.sessionStorage.setItem(
      WIZARD_SESSION_STORAGE_KEY,
      JSON.stringify("just a string"),
    );
    expect(loadWizardSession()).toBeNull();
  });
});

describe("clearWizardSession", () => {
  it("removes a saved session so a later load finds nothing", () => {
    saveWizardSession(DRAFT, 1, 1);
    expect(loadWizardSession()).not.toBeNull();

    clearWizardSession();

    expect(loadWizardSession()).toBeNull();
  });

  it("is a no-op when nothing was ever saved", () => {
    expect(() => clearWizardSession()).not.toThrow();
  });
});
