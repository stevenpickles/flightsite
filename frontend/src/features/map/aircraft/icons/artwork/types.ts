/**
 * The vocabulary every silhouette is drawn in.
 *
 * Artwork is a *function of its colours* rather than markup with a fixed fill:
 * the palette is applied by construction when the icon is rendered, so a tint
 * (military, government) cannot drift from the civil drawing and no path can
 * forget to take its fill from the palette — the type system will not let a
 * drawing be written any other way.
 *
 * Drawing rules the layer depends on (`silhouettes.ts` documents why):
 *
 * - 64 × 64 canvas, nose pointing north (up), balanced about (32, 32).
 * - Body fill with a 2 px ink casing on every filled part, so the shape reads
 *   on the dark aviation basemap, the light one, and raster imagery alike.
 * - Draw order is meaning: a high wing is drawn *over* the fuselage so its
 *   outline runs unbroken across the body; a low wing is drawn *under* it so
 *   the fuselage interrupts the wing. That is how a Cessna and a Piper are
 *   told apart at thirty pixels.
 */

export interface PaletteColours {
  /** Body fill. */
  body: string;
  /** Outline / casing, and the colour of any purely linear detail (a boom, a
   * fin, a propeller bar). */
  ink: string;
}

/** Inner SVG markup for one silhouette — no `<svg>` wrapper. */
export type IconArtwork = (colours: PaletteColours) => string;

/** Casing weight on every filled part. */
export const CASING = 2;

/** A filled, cased part. */
export function part(d: string, c: PaletteColours): string {
  return (
    `<path d="${d}" fill="${c.body}" stroke="${c.ink}" ` +
    `stroke-width="${CASING}" stroke-linejoin="round"/>`
  );
}

/** A purely linear detail in ink — a propeller bar, a boom, a canted fin. */
export function line(d: string, c: PaletteColours, width: number): string {
  return (
    `<path d="${d}" fill="none" stroke="${c.ink}" stroke-width="${width}" ` +
    `stroke-linecap="round" stroke-linejoin="round"/>`
  );
}

/** A cased rounded rectangle centred on `cx` — an engine pod or a nacelle. */
export function pod(
  cx: number,
  top: number,
  bottom: number,
  width: number,
  c: PaletteColours,
): string {
  const x = cx - width / 2;
  const r = width / 2;
  return (
    `<rect x="${x}" y="${top}" width="${width}" height="${bottom - top}" rx="${r}" ` +
    `fill="${c.body}" stroke="${c.ink}" stroke-width="${CASING}"/>`
  );
}

/** A cased ellipse — a cabin, a sensor nose, a cockpit bulge. */
export function blob(
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  c: PaletteColours,
): string {
  return (
    `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" ` +
    `fill="${c.body}" stroke="${c.ink}" stroke-width="${CASING}"/>`
  );
}

/** A propeller seen edge-on: a short ink bar across the nose or nacelle. */
export function propeller(
  cx: number,
  y: number,
  half: number,
  c: PaletteColours,
): string {
  return line(`M${cx - half} ${y}h${half * 2}`, c, 2.5);
}

/**
 * A rotor disc: a thin cased ring for the swept area and two crossed blades —
 * ink under, body over, like every other part — so both stay legible on
 * either basemap. The ring is translucent so the airframe under it still
 * reads.
 */
export function rotor(
  cx: number,
  cy: number,
  r: number,
  c: PaletteColours,
): string {
  const k = r * Math.SQRT1_2;
  const blades =
    `M${cx - k} ${cy - k}L${cx + k} ${cy + k}` +
    `M${cx + k} ${cy - k}L${cx - k} ${cy + k}`;
  return (
    `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${c.ink}" ` +
    `stroke-width="3" opacity="0.8"/>` +
    `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${c.body}" ` +
    `stroke-width="1.25" opacity="0.8"/>` +
    line(blades, c, 4.5) +
    `<path d="${blades}" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>`
  );
}
