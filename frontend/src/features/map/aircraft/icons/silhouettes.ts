/**
 * FlightSite's aircraft silhouettes — original artwork, MIT-licensed with the
 * repository (`docs/LICENSES.md`).
 *
 * Drawn as SVG markup rather than shipped as files because they are tiny,
 * because MapLibre wants them as raster images registered with `addImage`
 * anyway, and because keeping them in TypeScript means the icon ids, the
 * artwork, and the resolver that chooses between them cannot drift apart. The
 * drawings themselves live in `./artwork/`, one file per family; this module
 * is the catalogue — which shapes exist, which palettes, and the image id
 * every (shape, palette) pair registers under.
 *
 * Drawing rules that the rest of the layer depends on:
 *
 * - **64 × 64 viewBox, nose pointing north (up).** MapLibre's `icon-rotate`
 *   turns an icon clockwise from north, so an icon drawn pointing up renders at
 *   the aircraft's `track_deg` with no offset.
 * - **Centred on (32, 32).** The symbol's anchor is its centre, so the icon
 *   must be balanced about that point or aircraft will appear offset from their
 *   reported positions — most visibly when rotating.
 * - **Light body, dark casing.** A pale fill with a dark outline reads on the
 *   dark aviation basemap, the light one, and OSM raster imagery, which is why
 *   the icons do not follow the app theme. The classification palettes keep
 *   the casing and tint only the body.
 * - **Relative size is in the artwork.** A glider and a 747 are drawn to
 *   different footprints inside the same canvas, so the symbol layer's one
 *   zoom-driven `icon-size` expression needs no per-shape multiplier.
 *
 * **Palettes are a secondary cue (SPEC §36).** The shape says what the
 * aircraft *is*; the tint says who flies it — military, government or civil —
 * and the same fact is always also stated in text (the detail panel, the
 * filters, the label's indicator), so nothing is communicated by colour alone.
 */

import { CIVIL_ARTWORK } from "@/features/map/aircraft/icons/artwork/civil";
import { GENERIC_ARTWORK } from "@/features/map/aircraft/icons/artwork/generic";
import { MILITARY_ARTWORK } from "@/features/map/aircraft/icons/artwork/military";
import { ROTORCRAFT_ARTWORK } from "@/features/map/aircraft/icons/artwork/rotorcraft";
import type {
  IconArtwork,
  PaletteColours,
} from "@/features/map/aircraft/icons/artwork/types";

/** Rendered pixel size of each icon. Registered at `pixelRatio: 2`, so this is
 * 32 CSS pixels of icon at `icon-size: 1`. */
export const ICON_PIXELS = 64;

/** The silhouettes the resolver can choose between. */
export type AircraftIconShape =
  | "generic"
  | "ground"
  | "light-high-wing"
  | "light-cirrus"
  | "light-low-wing"
  | "light-twin"
  | "turboprop-twin"
  | "business-jet"
  | "narrowbody"
  | "widebody-twin"
  | "widebody-quad"
  | "fighter"
  | "bomber"
  | "tanker"
  | "military-transport"
  | "patrol"
  | "uav"
  | "rotorcraft"
  | "tiltrotor"
  | "tandem-rotor"
  | "glider";

/** Every shape's drawing. `satisfies` makes a shape with no artwork — or
 * artwork for a shape the union does not name — a compile error. */
const ARTWORK = {
  ...GENERIC_ARTWORK,
  ...CIVIL_ARTWORK,
  ...MILITARY_ARTWORK,
  ...ROTORCRAFT_ARTWORK,
} satisfies Record<AircraftIconShape, IconArtwork>;

/** Every shape, in catalogue order. */
export const AIRCRAFT_ICON_SHAPES: readonly AircraftIconShape[] = Object.keys(
  ARTWORK,
) as AircraftIconShape[];

/**
 * Who flies it. `civil` is the original palette; `military` and `government`
 * (which also covers law enforcement) tint the body and keep the casing.
 * Precedence between them is `resolveIconPalette`'s business.
 */
export type IconPalette = "civil" | "military" | "government";

/** Dark casing — legible against light basemaps and raster imagery. Shared by
 * every palette so the tinted bodies stay as readable as the pale one. */
const INK = "#0b1220";

export const ICON_PALETTES: Readonly<Record<IconPalette, PaletteColours>> = {
  /** Pale body — legible against the dark aviation basemap. */
  civil: { body: "#f2f6ff", ink: INK },
  /** Olive-khaki. */
  military: { body: "#b9c79a", ink: INK },
  /** Cool blue. */
  government: { body: "#9fc8ff", ink: INK },
};

export const ICON_PALETTE_NAMES: readonly IconPalette[] = Object.keys(
  ICON_PALETTES,
) as IconPalette[];

/** Position-source ring accent (MLAT). Colour is the *secondary* signal here;
 * the dashes are the primary one (SPEC §36 forbids relying on colour alone). */
const MLAT_ACCENT = "#ffd479";

function svg(body: string): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON_PIXELS}" height="${ICON_PIXELS}" ` +
    `viewBox="0 0 ${ICON_PIXELS} ${ICON_PIXELS}">${body}</svg>`
  );
}

/** One silhouette in one palette, as a standalone SVG document. */
export function renderIconSvg(shape: AircraftIconShape, palette: IconPalette): string {
  return svg(ARTWORK[shape](ICON_PALETTES[palette]));
}

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

/** MapLibre image id for one silhouette in one palette. Namespaced so it
 * cannot collide with a basemap style's own sprite entries; the double dash
 * keeps the palette unambiguous against shape names that contain a dash. */
export function iconImageId(shape: AircraftIconShape, palette: IconPalette = "civil"): string {
  return `flightsite-aircraft-${shape}--${palette}`;
}

/** Image id of the MLAT ring, which is a layer-wide constant rather than a
 * per-feature choice. */
export const MLAT_RING_IMAGE_ID = "flightsite-aircraft-mlat-ring";

function renderAll(): Record<string, string> {
  const images: Record<string, string> = {};
  for (const shape of AIRCRAFT_ICON_SHAPES) {
    for (const palette of ICON_PALETTE_NAMES) {
      images[iconImageId(shape, palette)] = renderIconSvg(shape, palette);
    }
  }
  images[MLAT_RING_IMAGE_ID] = svg(MLAT_RING);
  return images;
}

/** Every icon this layer registers — each shape in each palette, plus the
 * MLAT ring — keyed by image id, as standalone SVG documents. */
export const AIRCRAFT_ICON_SVGS: Readonly<Record<string, string>> = renderAll();
