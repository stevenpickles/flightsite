import type { NotificationConfig, UnitSystem } from "@/lib/api/config";

/**
 * The wizard's working copy of the config document. Numeric fields stay as
 * strings so every step is a normal controlled `<input>` — parsing and
 * bounds-checking happen in `lib/validation.ts`, and the final patch is
 * assembled from this shape in `lib/draft.ts`.
 */
export interface WizardDraft {
  siteName: string;
  latitude: string;
  longitude: string;
  antennaHeightFt: string;

  receiverHost: string;
  receiverPort: string;
  receiverPath: string;
  pollIntervalS: string;

  units: UnitSystem;
  timezone: string;

  notifications: NotificationConfig;

  /** Raw text typed into the AeroDataBox key field. Never prefilled with
   * the real secret — only ever empty, or whatever the user just typed. */
  aerodataboxKeyInput: string;
  /** Whether the user has interacted with the key field this session. An
   * untouched field is omitted from the submitted patch entirely, so a
   * previously-stored key is never disturbed just by revisiting the step. */
  aerodataboxKeyTouched: boolean;
  aerodataboxEnabled: boolean;

  enabledTemplateIds: string[];
}

export type DecoderTestStatus = "idle" | "testing" | "success" | "error";

/** Ephemeral (non-persisted) state for the decoder connection test — kept
 * separate from `WizardDraft` because it describes the *last test run*,
 * not a config value, and resets whenever the tested fields change. */
export interface DecoderTestState {
  status: DecoderTestStatus;
  /** `true` once the user has explicitly chosen to skip the test — a
   * deliberate escape hatch (SPEC: the decoder may be offline during
   * setup), distinct from simply never having run one. */
  skipped: boolean;
  /** Human-readable detail for the last outcome — a success summary
   * ("readsb, 37 aircraft, 24 with positions") or the failure detail from
   * `ConnectionTestResult`. `null` while idle/testing or once skipped. */
  message: string | null;
}

export const INITIAL_DECODER_TEST_STATE: DecoderTestState = {
  status: "idle",
  skipped: false,
  message: null,
};
