/** A small curated fallback used only when the runtime does not implement
 * `Intl.supportedValuesOf` (older engines) — covers one representative
 * zone per populated UTC offset band so the select is still usable. */
const FALLBACK_TIMEZONES: readonly string[] = [
  "UTC",
  "America/Anchorage",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Bangkok",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Australia/Sydney",
  "Pacific/Auckland",
];

/** Lists every IANA timezone the runtime knows about, alphabetically.
 * `Intl.supportedValuesOf("timeZone")` is available in every browser this
 * project targets and in Node 22+; the fallback list only matters for an
 * unusually old engine. */
export function listTimezones(): readonly string[] {
  const supportedValuesOf = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf;
  if (typeof supportedValuesOf === "function") {
    try {
      const zones = supportedValuesOf("timeZone");
      if (zones.length > 0) {
        return zones;
      }
    } catch {
      // Fall through to the fallback list below.
    }
  }
  return FALLBACK_TIMEZONES;
}

/** Best-effort browser-reported IANA timezone, used to pre-fill the wizard
 * for a fresh install. Falls back to `"UTC"` — the same default the
 * backend settings model uses — if detection throws. */
export function detectBrowserTimezone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone && zone.length > 0 ? zone : "UTC";
  } catch {
    return "UTC";
  }
}
