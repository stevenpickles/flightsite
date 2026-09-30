/**
 * Plain-language names for the emergency kinds (roadmap slice 086).
 *
 * An aircraft declares an emergency two ways: an emergency squawk
 * (7500/7600/7700) or the ADS-B emergency/priority status the decoder reports
 * as `decoder_emergency`. The backend names both with one vocabulary of
 * *kinds* — `docs/API.md` §2.8's `emergency_kind`, which is the
 * `decoder_emergency` vocabulary — so squawk 7600 and a decoder's `nordo` are
 * the same kind, "No radio". This module is where that vocabulary becomes
 * English, once, for the detail panel's badge, the activity feed and browser
 * notifications alike: three surfaces describing one emergency must not use
 * three different words for it.
 *
 * Every lookup degrades: a kind this build has never heard of (a backend that
 * learned a new one, §6) yields `null` rather than a raw slug, and callers
 * fall back to their generic wording.
 */

import type { DecoderEmergency } from "@/lib/api/live";

/** `emergency_kind` / `decoder_emergency` → the words a person reads. */
export const EMERGENCY_KIND_LABELS: Readonly<Record<DecoderEmergency, string>> =
  {
    general: "General emergency",
    lifeguard: "Lifeguard / medical",
    minfuel: "Minimum fuel",
    nordo: "No radio",
    unlawful: "Unlawful interference",
    downed: "Downed",
  };

/** The label for an emergency kind, or `null` for an absent or unknown one. */
export function emergencyKindLabel(
  kind: string | null | undefined,
): string | null {
  if (typeof kind !== "string") {
    return null;
  }
  return Object.hasOwn(EMERGENCY_KIND_LABELS, kind)
    ? EMERGENCY_KIND_LABELS[kind as DecoderEmergency]
    : null;
}

/**
 * The headline for an `emergency_squawk` activity event, shared by the feed
 * and by browser notifications so the two never word one emergency
 * differently.
 *
 * - Declared by the decoder (`emergency_source: "decoder"`): the kind leads —
 *   "Emergency: Minimum fuel" — because there is no code to show; the
 *   transponder was on an ordinary one.
 * - Declared by a squawk: the code leads, as it always has, with the kind
 *   after it when the payload names one — "Emergency squawk 7600 · No radio".
 * - A payload predating slice 086 carries neither `emergency_source` nor
 *   `emergency_kind`, and reads exactly as it did before.
 */
export function emergencyHeadline(
  squawk: string | null,
  source: string | null,
  kind: string | null,
): string {
  const label = emergencyKindLabel(kind);
  if (source === "decoder" || squawk === null) {
    if (label !== null) {
      return `Emergency: ${label}`;
    }
    return source === "decoder" ? "Emergency declared" : "Emergency squawk";
  }
  return label === null
    ? `Emergency squawk ${squawk}`
    : `Emergency squawk ${squawk} · ${label}`;
}
