import { describe, expect, it } from "vitest";

import {
  buildAlertsPatch,
  buildDecoderPatch,
  buildDisplayPatch,
  buildEnrichmentPatch,
  buildMetadataPatch,
  buildNotificationsPatch,
  buildReceiverPatch,
  buildRetentionPatch,
  buildUnitsAndTimePatch,
  draftFromConfig,
  isSectionDirty,
  pickAlerts,
  pickDecoder,
  pickDisplay,
  pickEnrichment,
  pickMetadata,
  pickNotifications,
  pickReceiverLocation,
  pickRetention,
  pickUnitsAndTime,
} from "@/features/settings/lib/draft";
import {
  defaultEnrichmentConfig,
  defaultFlightSiteConfig,
} from "@/test/configApiMock";

describe("draftFromConfig", () => {
  it("carries every server section into its corresponding draft field", () => {
    const draft = draftFromConfig(
      defaultFlightSiteConfig({
        units: "metric",
        timezone: "Europe/London",
        display_radius_nm: 300,
        alert_radius_nm: 150,
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
        map: {
          basemap: "light-aviation",
          range_rings_enabled: false,
          range_ring_radii_nm: [25, 75],
        },
        retention: { high_res_metric_days: 21 },
        alerts: { enabled_templates: ["watchlist"] },
      }),
    );

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
    expect(draft.displayRadiusNm).toBe("300");
    expect(draft.alertRadiusNm).toBe("150");
    expect(draft.basemap).toBe("light-aviation");
    expect(draft.rangeRingsEnabled).toBe(false);
    expect(draft.rangeRingRadiiNm).toBe("25, 75");
    expect(draft.highResMetricDays).toBe("21");
    expect(draft.enabledTemplateIds).toEqual(["watchlist"]);
  });

  it("leaves alert radius blank when unlimited (null)", () => {
    const draft = draftFromConfig(
      defaultFlightSiteConfig({ alert_radius_nm: null }),
    );
    expect(draft.alertRadiusNm).toBe("");
  });

  it("never prefills the AeroDataBox key input, even when one is stored", () => {
    const draft = draftFromConfig(
      defaultFlightSiteConfig({
        enrichment: defaultEnrichmentConfig({
          aerodatabox_enabled: true,
          aerodatabox_api_key: "•••",
        }),
      }),
    );
    expect(draft.aerodataboxKeyInput).toBe("");
    expect(draft.aerodataboxKeyTouched).toBe(false);
    expect(draft.aerodataboxEnabled).toBe(true);
  });
});

describe("isSectionDirty", () => {
  it("is false for structurally equal slices", () => {
    expect(isSectionDirty({ a: 1, b: [1, 2] }, { a: 1, b: [1, 2] })).toBe(
      false,
    );
  });

  it("is true once a field differs", () => {
    expect(isSectionDirty({ a: 1 }, { a: 2 })).toBe(true);
  });
});

describe("buildReceiverPatch", () => {
  it("builds the location patch, trimming and parsing numbers", () => {
    const draft = pickReceiverLocation(
      draftFromConfig(
        defaultFlightSiteConfig({
          location: {
            latitude: 47.6,
            longitude: -122.3,
            site_name: "  Home  ",
            antenna_height_ft: null,
          },
        }),
      ),
    );
    const patch = buildReceiverPatch({ ...draft, siteName: "  Home  " });
    expect(patch.location).toEqual({
      site_name: "Home",
      latitude: 47.6,
      longitude: -122.3,
      antenna_height_ft: null,
    });
  });
});

describe("buildDecoderPatch", () => {
  it("builds the receiver patch with a truncated integer port", () => {
    const draft = pickDecoder(draftFromConfig(defaultFlightSiteConfig()));
    const patch = buildDecoderPatch({ ...draft, receiverPort: "8080.9" });
    expect(patch.receiver).toEqual({
      host: "127.0.0.1",
      port: 8080,
      path: "/data/aircraft.json",
      poll_interval_s: 1,
    });
  });
});

describe("buildUnitsAndTimePatch", () => {
  it("builds a units + timezone patch", () => {
    const draft = pickUnitsAndTime(
      draftFromConfig(defaultFlightSiteConfig({ units: "metric" })),
    );
    expect(buildUnitsAndTimePatch(draft)).toEqual({
      units: "metric",
      timezone: "UTC",
    });
  });
});

describe("buildDisplayPatch", () => {
  it("parses the comma-separated radii list", () => {
    const draft = pickDisplay(draftFromConfig(defaultFlightSiteConfig()));
    const patch = buildDisplayPatch({
      ...draft,
      rangeRingRadiiNm: "50, 100, 150,",
    });
    expect(patch.map).toEqual({
      basemap: "dark-aviation",
      range_rings_enabled: true,
      range_ring_radii_nm: [50, 100, 150],
    });
  });
});

describe("buildAlertsPatch", () => {
  it("sends null for a blank alert radius (unlimited)", () => {
    const draft = pickAlerts(
      draftFromConfig(defaultFlightSiteConfig({ alert_radius_nm: null })),
    );
    const patch = buildAlertsPatch(draft);
    expect(patch.alert_radius_nm).toBeNull();
  });

  it("sends the parsed number for a set alert radius", () => {
    const draft = pickAlerts(draftFromConfig(defaultFlightSiteConfig()));
    const patch = buildAlertsPatch({ ...draft, alertRadiusNm: "200" });
    expect(patch.alert_radius_nm).toBe(200);
  });
});

describe("buildNotificationsPatch", () => {
  it("round-trips the notifications document", () => {
    const draft = pickNotifications(draftFromConfig(defaultFlightSiteConfig()));
    expect(buildNotificationsPatch(draft).notifications).toEqual(
      draft.notifications,
    );
  });
});

describe("buildEnrichmentPatch", () => {
  const base = pickEnrichment(draftFromConfig(defaultFlightSiteConfig()));

  it("omits the key entirely when untouched", () => {
    const patch = buildEnrichmentPatch(base);
    expect(patch.enrichment).toEqual({
      aerodatabox_enabled: false,
      daily_lookup_budget: 0,
      route_ttl_days: 7,
    });
    expect(patch.enrichment).not.toHaveProperty("aerodatabox_api_key");
  });

  it("sends the typed key when touched with a value", () => {
    const patch = buildEnrichmentPatch({
      ...base,
      aerodataboxKeyTouched: true,
      aerodataboxKeyInput: "sk-new-key",
      aerodataboxEnabled: true,
    });
    expect(patch.enrichment).toEqual({
      aerodatabox_enabled: true,
      aerodatabox_api_key: "sk-new-key",
      daily_lookup_budget: 0,
      route_ttl_days: 7,
    });
  });

  it("sends null to explicitly clear a stored key", () => {
    const patch = buildEnrichmentPatch({
      ...base,
      aerodataboxKeyTouched: true,
      aerodataboxKeyInput: "",
      aerodataboxEnabled: false,
    });
    expect(patch.enrichment).toEqual({
      aerodatabox_enabled: false,
      aerodatabox_api_key: null,
      daily_lookup_budget: 0,
      route_ttl_days: 7,
    });
  });
});

describe("buildRetentionPatch", () => {
  it("builds a truncated integer retention patch", () => {
    const draft = pickRetention(draftFromConfig(defaultFlightSiteConfig()));
    const patch = buildRetentionPatch({ ...draft, highResMetricDays: "21" });
    expect(patch.retention).toEqual({ high_res_metric_days: 21 });
  });
});

describe("buildMetadataPatch", () => {
  it("sends the opensky flag unconditionally", () => {
    expect(buildMetadataPatch({ openskyEnabled: true })).toEqual({
      metadata: { opensky_enabled: true },
    });
    expect(buildMetadataPatch({ openskyEnabled: false })).toEqual({
      metadata: { opensky_enabled: false },
    });
  });

  it("carries no other section, so saving it cannot disturb one", () => {
    expect(Object.keys(buildMetadataPatch({ openskyEnabled: true }))).toEqual([
      "metadata",
    ]);
  });
});

describe("pickMetadata", () => {
  it("round-trips the stored value out of a config document", () => {
    const draft = draftFromConfig(
      defaultFlightSiteConfig({ metadata: { opensky_enabled: true } }),
    );

    expect(pickMetadata(draft)).toEqual({ openskyEnabled: true });
  });

  it("defaults to off, matching the backend default (ADR-0013)", () => {
    expect(pickMetadata(draftFromConfig(defaultFlightSiteConfig()))).toEqual({
      openskyEnabled: false,
    });
  });
});
