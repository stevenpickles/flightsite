import { describe, expect, it } from "vitest";

import { DEFAULT_ENABLED_TEMPLATE_IDS } from "@/features/setup/constants";
import { buildConfigPatch, draftFromConfig } from "@/features/setup/lib/draft";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

describe("draftFromConfig", () => {
  it("carries every server value into its corresponding draft field", () => {
    const draft = draftFromConfig({
      first_run: false,
      config: defaultFlightSiteConfig({
        units: "metric",
        timezone: "Europe/London",
        location: {
          latitude: 51.5,
          longitude: -0.12,
          site_name: "Home Roof",
          antenna_height_ft: 30,
        },
        receiver: {
          host: "10.0.0.5",
          port: 8081,
          path: "/dump1090-fa/data/aircraft.json",
          poll_interval_s: 2,
        },
      }),
      secrets_set: { "enrichment.aerodatabox_api_key": false },
    });

    expect(draft.siteName).toBe("Home Roof");
    expect(draft.latitude).toBe("51.5");
    expect(draft.longitude).toBe("-0.12");
    expect(draft.antennaHeightFt).toBe("30");
    expect(draft.receiverHost).toBe("10.0.0.5");
    expect(draft.receiverPort).toBe("8081");
    expect(draft.receiverPath).toBe("/dump1090-fa/data/aircraft.json");
    expect(draft.pollIntervalS).toBe("2");
    expect(draft.units).toBe("metric");
    expect(draft.timezone).toBe("Europe/London");
  });

  it("leaves numeric location fields blank when unset", () => {
    const draft = draftFromConfig({
      first_run: true,
      config: defaultFlightSiteConfig(),
      secrets_set: { "enrichment.aerodatabox_api_key": false },
    });
    expect(draft.latitude).toBe("");
    expect(draft.longitude).toBe("");
    expect(draft.antennaHeightFt).toBe("");
  });

  it("defaults enabledTemplateIds when the server has none configured yet", () => {
    const draft = draftFromConfig({
      first_run: true,
      config: defaultFlightSiteConfig(),
      secrets_set: { "enrichment.aerodatabox_api_key": false },
    });
    expect(draft.enabledTemplateIds).toEqual(DEFAULT_ENABLED_TEMPLATE_IDS);
  });

  it("preserves an already-configured template selection instead of the defaults", () => {
    const draft = draftFromConfig({
      first_run: false,
      config: defaultFlightSiteConfig({
        alerts: { enabled_templates: ["watchlist"] },
      }),
      secrets_set: { "enrichment.aerodatabox_api_key": false },
    });
    expect(draft.enabledTemplateIds).toEqual(["watchlist"]);
  });

  it("never prefills the AeroDataBox key input, even when one is stored", () => {
    const draft = draftFromConfig({
      first_run: false,
      config: defaultFlightSiteConfig({
        enrichment: { aerodatabox_enabled: true, aerodatabox_api_key: "•••" },
      }),
      secrets_set: { "enrichment.aerodatabox_api_key": true },
    });
    expect(draft.aerodataboxKeyInput).toBe("");
    expect(draft.aerodataboxKeyTouched).toBe(false);
    expect(draft.aerodataboxEnabled).toBe(true);
  });
});

describe("buildConfigPatch", () => {
  const baseDraft = draftFromConfig({
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

  it("includes location, receiver, units, timezone, notifications, and alerts", () => {
    const patch = buildConfigPatch(baseDraft);
    expect(patch.location).toEqual({
      site_name: "Home",
      latitude: 47.6,
      longitude: -122.3,
      antenna_height_ft: null,
    });
    expect(patch.receiver).toEqual({
      host: "127.0.0.1",
      port: 8080,
      path: "/data/aircraft.json",
      poll_interval_s: 1,
    });
    expect(patch.units).toBe("aviation");
    expect(patch.timezone).toBe(baseDraft.timezone);
    expect(patch.notifications).toEqual(baseDraft.notifications);
    expect(patch.alerts).toEqual({
      enabled_templates: baseDraft.enabledTemplateIds,
    });
  });

  it("omits the AeroDataBox key entirely when the field was never touched", () => {
    const patch = buildConfigPatch(baseDraft);
    expect(patch.enrichment).toEqual({ aerodatabox_enabled: false });
    expect(patch.enrichment).not.toHaveProperty("aerodatabox_api_key");
  });

  it("sends the typed key when the field was touched with a value", () => {
    const patch = buildConfigPatch({
      ...baseDraft,
      aerodataboxKeyTouched: true,
      aerodataboxKeyInput: "sk-new-key",
      aerodataboxEnabled: true,
    });
    expect(patch.enrichment).toEqual({
      aerodatabox_enabled: true,
      aerodatabox_api_key: "sk-new-key",
    });
  });

  it("sends null to clear a touched-but-emptied key", () => {
    const patch = buildConfigPatch({
      ...baseDraft,
      aerodataboxKeyTouched: true,
      aerodataboxKeyInput: "",
      aerodataboxEnabled: false,
    });
    expect(patch.enrichment).toEqual({
      aerodatabox_enabled: false,
      aerodatabox_api_key: null,
    });
  });
});
