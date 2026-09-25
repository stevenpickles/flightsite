/**
 * Shared display vocabulary for a metadata source name (`"mictronics"`,
 * `"faa"`, `"opensky"`, `"airports"`, `"routes"`, `"demo"`, …) — the string
 * `GET /api/internal/metadata/status` and the `/api/v1/diagnostics`
 * `metadata.sources` list both key rows by (roadmap slice 025, SPEC §67).
 *
 * R4-14: this used to live only inside `features/settings/sections/
 * MetadataSection.tsx`, so the Health page's "Metadata datasets" card
 * printed the raw source name lower-case (`"faa"`, `"18 rows"`) while
 * Settings, reading the same names, printed `"FAA"` and `"18 aircraft"` —
 * the same concept named two different ways on two pages, which the
 * rubric's §4 explicitly calls out. Pulling the maps out here is what lets
 * both pages read from one place instead of drifting again the next time a
 * source is added.
 */

/** Display names for sources whose own name does not read as one.
 *
 * `airports` is deliberately absent: capitalising it gives "Airports",
 * which is exactly right, and a map entry restating that would be one more
 * thing to keep in step. `routes` cannot fall through the same way —
 * "Routes" would not say whose routes these are, and slice 071 makes the
 * answer part of the point: they come from an offline directory this
 * install holds, not from the online provider configured under
 * Enrichment. `demo` is the source demo mode registers in place of the
 * real importers. */
const SOURCE_LABELS: Record<string, string> = {
  mictronics: "Mictronics",
  faa: "FAA",
  opensky: "OpenSky",
  routes: "Flight routes (VRS)",
  demo: "Demo",
};

/** A metadata source's display name — its entry in {@link SOURCE_LABELS},
 * or its own name capitalized for anything not listed there (which is
 * already correct for `airports`, and fails safe — a readable label rather
 * than a thrown error — for a source a future slice adds and this list has
 * not caught up with yet). */
export function sourceLabel(name: string): string {
  return SOURCE_LABELS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}

/** What a source's `row_count` counts. Sources not named here count
 * airframes, which is what every source counted before slice 027. */
const SOURCE_ROW_NOUNS: Record<string, string> = {
  airports: "airports",
  routes: "routes",
};

/** The noun a source's row count is counting — "18 aircraft" rather than
 * the generic, unitless "18 rows" the Health page printed before R4-14. */
export function rowNoun(name: string): string {
  return SOURCE_ROW_NOUNS[name] ?? "aircraft";
}
