/**
 * Registers the silhouettes with a MapLibre style as named images.
 *
 * A symbol layer draws whatever `icon-image` names, and the name has to have
 * been registered on *that style* — `setStyle` (a basemap switch) discards
 * registered images along with the layers, so this runs again after every style
 * load, exactly like `ensureOverlayLayers`.
 *
 * The SVG is handed to the browser as a data URI and decoded through an
 * `Image`, which is the only route from vector markup to the raster MapLibre
 * needs without shipping a rasteriser. `pixelRatio: 2` tells MapLibre the
 * 64-pixel bitmap is 32 CSS pixels of icon, so it stays crisp on a HiDPI
 * display.
 *
 * The image constructor is injectable because jsdom does not decode images;
 * tests substitute a loader that resolves immediately and assert on what was
 * registered rather than on a browser's decoding.
 */

import type { StyleImageSource } from "maplibre-gl";

import type { AircraftIconShape } from "@/features/map/aircraft/icons/silhouettes";
import {
  AIRCRAFT_ICON_SVGS,
  iconImageId,
} from "@/features/map/aircraft/icons/silhouettes";

/** Pixel ratio the icons are registered at — see the module docstring. */
export const ICON_PIXEL_RATIO = 2;

/** Encodes SVG markup as a data URI an `Image` can load.
 *
 * `encodeURIComponent` rather than base64: the markup is ASCII, the encoded
 * form stays readable in a devtools network panel, and it avoids the
 * `btoa`-and-Unicode trap entirely. */
export function svgDataUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** Loads one data URI into something `map.addImage` accepts. */
export type ImageLoader = (dataUri: string) => Promise<StyleImageSource>;

/** The two style methods icon registration needs. Declared structurally rather
 * than as a `Pick` of MapLibre's `Map` so a test can supply a plain object
 * without reproducing the real class's chainable return types. */
export interface IconImageRegistry {
  hasImage(id: string): boolean;
  addImage(
    id: string,
    image: StyleImageSource,
    options?: { pixelRatio?: number },
  ): unknown;
}

/** Decodes a data URI through a plain `Image` element. Exported so other
 * icon sets registered the same way (the airport overlay's size-class
 * glyphs, `features/map/overlays/airportIcons.ts`) can reuse the identical
 * loader rather than reimplementing this decode-and-reject dance. */
export const loadViaImageElement: ImageLoader = (dataUri) =>
  new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve(image);
    };
    image.onerror = () => {
      reject(new Error("failed to decode icon"));
    };
    image.src = dataUri;
  });

/** Every image id this layer needs, in registration order. */
export const AIRCRAFT_ICON_NAMES: readonly (AircraftIconShape | "mlat-ring")[] =
  ["airliner", "rotorcraft", "ground", "mlat-ring"];

/**
 * Ensures every aircraft icon is registered on `map`'s current style.
 *
 * Idempotent: an image the style already carries is skipped, so calling this
 * again after a style load costs one `hasImage` check per icon. Resolves once
 * every icon is present, which is what the caller waits on before adding the
 * symbol layers — a layer whose `icon-image` is not yet registered renders
 * nothing and logs a warning per feature per frame.
 */
export async function registerAircraftIcons(
  map: IconImageRegistry,
  loadImage: ImageLoader = loadViaImageElement,
): Promise<void> {
  await Promise.all(
    AIRCRAFT_ICON_NAMES.map(async (name) => {
      const id = iconImageId(name);
      if (map.hasImage(id)) {
        return;
      }
      const image = await loadImage(svgDataUri(AIRCRAFT_ICON_SVGS[name]));
      // Re-checked after the await: two concurrent style loads could both have
      // passed the first check, and `addImage` throws on a duplicate id.
      if (!map.hasImage(id)) {
        map.addImage(id, image, { pixelRatio: ICON_PIXEL_RATIO });
      }
    }),
  );
}
