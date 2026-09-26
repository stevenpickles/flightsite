import type {
  FeederKind,
  NotificationConfig,
  UnitSystem,
} from "@/lib/api/config";

/**
 * One row of the Feeders section's entries editor. Numeric/kind-dependent
 * fields stay strings, same rationale as every other draft field
 * (`lib/validation.ts` owns bounds-checking); fields a given `kind` does
 * not use are simply left blank and dropped by `buildFeedersPatch` rather
 * than validated.
 *
 * The stats-URL trio mirrors `aerodataboxKeyInput` /
 * `aerodataboxKeyTouched` exactly, once per row instead of once per
 * section: always empty on load, `statsUrlTouched` gates whether the row's
 * entry is even present in a save's `feeders.stats_urls` patch, and
 * `statsUrlStored` is this row's own reading of
 * `secrets_set["feeders.stats_urls.<name>"]` — tracked per row (by the
 * entry's `name` at load/save time) because the section holds a table of
 * these, not one secret.
 */
export interface FeederEntryDraft {
  name: string;
  label: string;
  kind: FeederKind;
  url: string;
  container: string;
  host: string;
  mlatPort: string;
  beastPort: string;
  webUrl: string;
  statsUrlInput: string;
  statsUrlTouched: boolean;
  statsUrlStored: boolean;
}

/** One row of the local-pages table — no probe, no secret, just a link. */
export interface LocalPageDraft {
  label: string;
  url: string;
}

/** The Feeders section's whole draft (roadmap slice 077). Applies on save
 * — the service rebuilds its probes from a new entry list, same as
 * `EnrichmentSection`'s provider rebuild, so this section carries no
 * restart badge either. */
export interface FeedersDraft {
  pollIntervalS: string;
  /** Blank means unset (`docker_socket: null`) — opt-in, off by default. */
  dockerSocket: string;
  entries: FeederEntryDraft[];
  localPages: LocalPageDraft[];
}

/**
 * The Settings page's working copy of the config document. Mirrors
 * `WizardDraft` (`@/features/setup/types`) in spirit — numeric fields stay
 * as strings so every field is a normal controlled `<input>`, with parsing
 * and bounds-checking in `lib/validation.ts` — but covers every section the
 * wizard does not manage (display, alert radius, map, retention) as well.
 */
export interface SettingsDraft {
  // Receiver location (SPEC §13). Restart-required to *change*: bearing,
  // distance and range rings are computed against the reference point the
  // running live store holds, so moving it would leave every aircraft
  // already observed carrying a distance measured from somewhere else until
  // it is next seen. Note this is about changing an established value — the
  // setup wizard's first save fills the blank in place and needs no restart
  // (`flightsite.api.internal._apply_receiver_location`).
  siteName: string;
  latitude: string;
  longitude: string;
  antennaHeightFt: string;

  // Decoder endpoint (SPEC §11). Restart-required to *change* for the
  // parallel reason: a running adapter owns its connection, its poll loop
  // and its health history, all of which belong to the endpoint it started
  // on. The first-run save, where there is no adapter yet, starts one in
  // place (`flightsite.api.ingestion`).
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
  // `enabled_templates` is deliberately absent here (R4-03): the Alerts
  // page's Templates gallery is the single control surface for shipped
  // templates (it resolves "added" from real rule provenance, which
  // `config.alerts.enabled_templates` cannot — see
  // `docs/reviews/2026-09-20-site-review.md` R4-03). The config key still
  // exists and is still read once, by the setup wizard, as the first-run
  // seed for which templates to instantiate.

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
  /** Provider lookups allowed per UTC day, as typed; "0" means unlimited. */
  dailyLookupBudget: string;
  /** How long a learned route stays usable, 1–30 days. */
  routeTtlDays: string;

  // Metadata sources.
  /** Whether the opt-in OpenSky aircraft database takes part in "Update
   * Aircraft Metadata" (ADR-0013). Off by default; applies on restart. */
  openskyEnabled: boolean;

  // Retention.
  highResMetricDays: string;

  // Feeders (slice 077).
  feeders: FeedersDraft;
}
