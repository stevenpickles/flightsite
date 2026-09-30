/**
 * ADS-B emitter categories in words (roadmap slice 086).
 *
 * An ADS-B transmitter broadcasts a two-character category for its own
 * airframe — `docs/API.md` §3.3's `emitter_category`, `"A0"`–`"D7"`. Set A is
 * powered aircraft by weight and performance, set B unpowered, lighter-than-air
 * and unmanned vehicles, set C surface vehicles and obstacles, and set D is
 * reserved. The code alone is jargon ("A3"), so every surface that shows one —
 * the detail panel, the filter drawer — shows it through this table, as
 * "A3 · Large aircraft", and they cannot drift into different words.
 *
 * All 32 codes are named, including the reserved and "no information" ones:
 * the backend passes the category through exactly as the aircraft sent it
 * (`backend/src/flightsite/ingest/readsb.py`), so an `A0` is a real value a
 * user can see and deserves a real label rather than a bare code.
 */

/** Every well-formed emitter category and its meaning. */
export const EMITTER_CATEGORY_LABELS: Readonly<Record<string, string>> = {
  A0: "No category information",
  A1: "Light aircraft",
  A2: "Small aircraft",
  A3: "Large aircraft",
  A4: "High-vortex large aircraft",
  A5: "Heavy aircraft",
  A6: "High-performance aircraft",
  A7: "Rotorcraft",
  B0: "No category information",
  B1: "Glider / sailplane",
  B2: "Lighter-than-air",
  B3: "Parachutist / skydiver",
  B4: "Ultralight / hang glider / paraglider",
  B5: "Reserved",
  B6: "Unmanned aerial vehicle",
  B7: "Space / trans-atmospheric vehicle",
  C0: "No category information",
  C1: "Surface emergency vehicle",
  C2: "Surface service vehicle",
  C3: "Point obstacle",
  C4: "Cluster obstacle",
  C5: "Line obstacle",
  C6: "Reserved",
  C7: "Reserved",
  D0: "Reserved",
  D1: "Reserved",
  D2: "Reserved",
  D3: "Reserved",
  D4: "Reserved",
  D5: "Reserved",
  D6: "Reserved",
  D7: "Reserved",
};

/** The meaning of `code`, or `null` when it is absent or not a category. */
export function emitterCategoryLabel(
  code: string | null | undefined,
): string | null {
  if (
    typeof code !== "string" ||
    !Object.hasOwn(EMITTER_CATEGORY_LABELS, code)
  ) {
    return null;
  }
  return EMITTER_CATEGORY_LABELS[code] ?? null;
}

/** `"A3"` → `"A3 · Large aircraft"`; `null` for an absent or unknown code. */
export function formatEmitterCategory(
  code: string | null | undefined,
): string | null {
  const label = emitterCategoryLabel(code);
  return label === null ? null : `${code} · ${label}`;
}
