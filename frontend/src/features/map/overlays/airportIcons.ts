/**
 * Original minimal glyphs for the airport-overlay symbol layer (roadmap
 * slice 028) — one shape per size class, registered with MapLibre the same
 * way `features/map/aircraft/icons/registerIcons.ts` registers the aircraft
 * silhouettes, reusing that module's SVG-data-URI and image-loading
 * plumbing directly rather than duplicating it.
 *
 * 32 x 32 viewBox, centred on (16, 16) — smaller than the aircraft
 * silhouettes' 64 x 64 (`aircraft/icons/silhouettes.ts`) because these sit
 * still (no rotation, no "nose north" rule) and read as a minimal
 * wayfinding mark rather than a silhouette. One accent color across every
 * class (amber — distinct from the teal range rings and the red receiver
 * marker) keeps the overlay restrained per `docs/PRODUCT.md` §6;
 * distinctness between size classes comes from the glyph's shape and
 * weight, not from color.
 */

import {
  ICON_PIXEL_RATIO,
  loadViaImageElement,
  svgDataUri,
  type IconImageRegistry,
  type ImageLoader,
} from "@/features/map/aircraft/icons/registerIcons";
import type { AirportSizeClass } from "@/lib/api/overlays";

const ACCENT = "#f2b134";
const PIXELS = 32;

function svg(body: string): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${PIXELS}" height="${PIXELS}" ` +
    `viewBox="0 0 ${PIXELS} ${PIXELS}">${body}</svg>`
  );
}

/** Large: a ringed dot — the "major hub" mark. */
const LARGE = svg(
  `<circle cx="16" cy="16" r="10" fill="none" stroke="${ACCENT}" stroke-width="2.5"/>` +
    `<circle cx="16" cy="16" r="4" fill="${ACCENT}"/>`,
);

/** Medium: a solid dot. */
const MEDIUM = svg(`<circle cx="16" cy="16" r="6" fill="${ACCENT}"/>`);

/** Small: a hollow dot. */
const SMALL = svg(
  `<circle cx="16" cy="16" r="4.5" fill="none" stroke="${ACCENT}" stroke-width="2"/>`,
);

/** Heliport: a ring around an "H". */
const HELIPORT = svg(
  `<circle cx="16" cy="16" r="8" fill="none" stroke="${ACCENT}" stroke-width="2"/>` +
    `<path d="M11 10.5v11M21 10.5v11M11 16h10" fill="none" stroke="${ACCENT}" ` +
    `stroke-width="2" stroke-linecap="round"/>`,
);

/** Every glyph this layer registers, keyed by the overlay's size-class
 * vocabulary. */
export const AIRPORT_ICON_SVGS: Readonly<Record<AirportSizeClass, string>> = {
  large: LARGE,
  medium: MEDIUM,
  small: SMALL,
  heliport: HELIPORT,
};

const AIRPORT_SIZE_CLASSES: readonly AirportSizeClass[] = [
  "large",
  "medium",
  "small",
  "heliport",
];

/** MapLibre image id for one size class's glyph. Namespaced so it cannot
 * collide with a basemap style's own sprite entries or the aircraft icons. */
export function airportIconImageId(sizeClass: AirportSizeClass): string {
  return `flightsite-airport-${sizeClass}`;
}

/**
 * Ensures every airport glyph is registered on `map`'s current style.
 *
 * Idempotent, and re-checks `hasImage` after the `await` for the same reason
 * `registerAircraftIcons` does: two concurrent style loads could both pass
 * the first check, and `addImage` throws on a duplicate id.
 */
export async function registerAirportIcons(
  map: IconImageRegistry,
  loadImage: ImageLoader = loadViaImageElement,
): Promise<void> {
  await Promise.all(
    AIRPORT_SIZE_CLASSES.map(async (sizeClass) => {
      const id = airportIconImageId(sizeClass);
      if (map.hasImage(id)) {
        return;
      }
      const image = await loadImage(svgDataUri(AIRPORT_ICON_SVGS[sizeClass]));
      if (!map.hasImage(id)) {
        map.addImage(id, image, { pixelRatio: ICON_PIXEL_RATIO });
      }
    }),
  );
}
