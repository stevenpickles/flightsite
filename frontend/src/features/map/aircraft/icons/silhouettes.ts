/**
 * FlightSite's aircraft silhouettes — original artwork, MIT-licensed with the
 * repository (`docs/LICENSES.md`).
 *
 * Drawn here as SVG markup rather than shipped as files because they are tiny,
 * because MapLibre wants them as raster images registered with `addImage`
 * anyway, and because keeping them in TypeScript means the icon ids, the
 * artwork, and the resolver that chooses between them cannot drift apart.
 *
 * Drawing rules that the rest of the layer depends on:
 *
 * - **64 × 64 viewBox, nose pointing north (up).** MapLibre's `icon-rotate`
 *   turns an icon clockwise from north, so an icon drawn pointing up renders at
 *   the aircraft's `track_deg` with no offset.
 * - **Centred on (32, 32).** The symbol's anchor is its centre, so the icon
 *   must be balanced about that point or aircraft will appear offset from their
 *   reported positions — most visibly when rotating.
 * - **Light body, dark casing.** A single palette has to read on the dark
 *   aviation basemap, the light one, and OSM raster imagery. A pale fill with a
 *   dark outline does that in every case, which is why the icons do not follow
 *   the app theme.
 */

/** Rendered pixel size of each icon. Registered at `pixelRatio: 2`, so this is
 * 32 CSS pixels of icon at `icon-size: 1`. */
export const ICON_PIXELS = 64;

/** Pale body fill — legible against the dark aviation basemap. */
const BODY = "#f2f6ff";
/** Dark casing — legible against light basemaps and raster imagery. */
const INK = "#0b1220";

/** Position-source ring accent (MLAT). Colour is the *secondary* signal here;
 * the dashes are the primary one (SPEC §36 forbids relying on colour alone). */
const MLAT_ACCENT = "#ffd479";

function svg(body: string): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON_PIXELS}" height="${ICON_PIXELS}" ` +
    `viewBox="0 0 ${ICON_PIXELS} ${ICON_PIXELS}">${body}</svg>`
  );
}

/**
 * Generic swept-wing aircraft: pointed nose, swept leading edges out to the
 * wingtips at y = 41, a straight trailing edge back to the fuselage, and a
 * tailplane. The default silhouette for anything airborne whose type and
 * category are unknown — which, until slice 024 supplies metadata, is
 * everything.
 */
const AIRLINER_PATH =
  "M32 4C34.2 4 36 8.2 36 13.5L36 25L60 41L60 47L36 39L36 50L43 56L43 60" +
  "L32 57L21 60L21 56L28 50L28 39L4 47L4 41L28 25L28 13.5C28 8.2 29.8 4 32 4Z";

/**
 * Rotorcraft: a stubby fuselage, a tail boom with a stabiliser, and a rotor
 * disc suggested by two crossed blades. Unreachable from live data alone — no
 * heuristic guesses at rotorcraft from position reports — and wired to the
 * `helicopter` / `rotorcraft` icon categories that slice 024's metadata will
 * start supplying.
 */
const ROTORCRAFT_BODY =
  `<path d="M29.5 33h5v17h-5z" fill="${BODY}" stroke="${INK}" stroke-width="2" stroke-linejoin="round"/>` +
  `<path d="M23 46h18v5H23z" fill="${BODY}" stroke="${INK}" stroke-width="2" stroke-linejoin="round"/>` +
  `<ellipse cx="32" cy="26" rx="9" ry="11" fill="${BODY}" stroke="${INK}" stroke-width="2"/>` +
  `<path d="M16 16 48 48M48 16 16 48" fill="none" stroke="${INK}" stroke-width="4.5" stroke-linecap="round" opacity="0.85"/>` +
  `<path d="M16 16 48 48M48 16 16 48" fill="none" stroke="${BODY}" stroke-width="2" stroke-linecap="round"/>`;

/**
 * On-the-ground variant: the same planform, drawn smaller, sitting on a ground
 * bar. Ground traffic is dense, slow, and rarely the thing a watcher is looking
 * at, so it reads as "parked/taxiing" at a glance and takes up less of the
 * apron than an airborne icon would.
 */
const GROUND_PATH =
  "M32 10C34 10 35.4 12.6 35.4 16.4L35.4 25L52 34L52 38.4L35.4 33.6L35.4 40" +
  "L40 44L40 47.4L32 45.4L24 47.4L24 44L28.6 40L28.6 33.6L12 38.4L12 34" +
  "L28.6 25L28.6 16.4C28.6 12.6 30 10 32 10Z";

const GROUND_BAR = "M14 53h36a2.5 2.5 0 0 1 0 5H14a2.5 2.5 0 0 1 0-5z";

function filledPath(d: string): string {
  return `<path d="${d}" fill="${BODY}" stroke="${INK}" stroke-width="2" stroke-linejoin="round"/>`;
}

/** The silhouettes the resolver can choose between. */
export type AircraftIconShape = "airliner" | "rotorcraft" | "ground";

/**
 * A dashed ring drawn under MLAT positions.
 *
 * MLAT positions are multilaterated from timing, not reported by the aircraft,
 * and SPEC §36 forbids communicating that with colour alone — so the signal is
 * the *dash pattern*, which survives greyscale, colour-vision deficiency, and a
 * washed-out screen in daylight. It sits on its own symbol layer with
 * viewport-aligned rotation so it stays a ring while the aircraft turns.
 */
const MLAT_RING =
  `<circle cx="32" cy="32" r="27" fill="none" stroke="${INK}" stroke-width="7" ` +
  `stroke-dasharray="8 8" stroke-linecap="round" opacity="0.75"/>` +
  `<circle cx="32" cy="32" r="27" fill="none" stroke="${MLAT_ACCENT}" stroke-width="3.5" ` +
  `stroke-dasharray="8 8" stroke-linecap="round"/>`;

/** Every icon this layer registers, as standalone SVG documents. */
export const AIRCRAFT_ICON_SVGS: Readonly<
  Record<AircraftIconShape | "mlat-ring", string>
> = {
  airliner: svg(filledPath(AIRLINER_PATH)),
  rotorcraft: svg(ROTORCRAFT_BODY),
  ground: svg(filledPath(GROUND_PATH) + filledPath(GROUND_BAR)),
  "mlat-ring": svg(MLAT_RING),
};

/** MapLibre image id for one icon. Namespaced so it cannot collide with a
 * basemap style's own sprite entries. */
export function iconImageId(name: AircraftIconShape | "mlat-ring"): string {
  return `flightsite-aircraft-${name}`;
}

/** Image id of the MLAT ring, which is a layer-wide constant rather than a
 * per-feature choice. */
export const MLAT_RING_IMAGE_ID = iconImageId("mlat-ring");
