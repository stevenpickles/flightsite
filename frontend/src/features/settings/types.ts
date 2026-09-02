import type { NotificationConfig, UnitSystem } from "@/lib/api/config";

/**
 * The Settings page's working copy of the config document. Mirrors
 * `WizardDraft` (`@/features/setup/types`) in spirit — numeric fields stay
 * as strings so every field is a normal controlled `<input>`, with parsing
 * and bounds-checking in `lib/validation.ts` — but covers every section the
 * wizard does not manage (display, alert radius, map, retention) as well.
 */
export interface SettingsDraft {
  // Receiver location (SPEC §13). Restart-required: ingestion reads the
  // receiver endpoint once at process startup (see `flightsite.app`), and
  // downstream bearing/distance/range-ring computation is anchored on
  // whatever location was effective at that time.
  siteName: string;
  latitude: string;
  longitude: string;
  antennaHeightFt: string;

  // Decoder endpoint (SPEC §11). Restart-required for the same reason as
  // the receiver location above.
  receiverHost: string;
  receiverPort: string;
  receiverPath: string;
  pollIntervalS: string;

  // Units & time.
  units: UnitSystem;
  timezone: string;

  // Display.
  displayRadiusNm: string;
  basemap: string;
  rangeRingsEnabled: boolean;
  /** Comma-separated nautical-mile radii, e.g. "50, 100, 150, 200". */
  rangeRingRadiiNm: string;

  // Alerts.
  /** Blank means unlimited (`alert_radius_nm: null`). */
  alertRadiusNm: string;
  enabledTemplateIds: string[];

  // Notifications.
  notifications: NotificationConfig;

  // Enrichment.
  aerodataboxEnabled: boolean;
  /** Raw text typed into the AeroDataBox key field. Never prefilled with
   * the real secret — only ever empty, or whatever the user just typed. */
  aerodataboxKeyInput: string;
  /** Whether the user has interacted with the key field (or its Clear
   * affordance) this session. An untouched field is omitted from the
   * submitted patch entirely, so a previously-stored key is never
   * disturbed just by opening the section. */
  aerodataboxKeyTouched: boolean;

  // Metadata sources.
  /** Whether the opt-in OpenSky aircraft database takes part in "Update
   * Aircraft Metadata" (ADR-0013). Off by default; applies on restart. */
  openskyEnabled: boolean;

  // Retention.
  highResMetricDays: string;
}
