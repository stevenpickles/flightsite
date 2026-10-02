import { describe, expect, it } from "vitest";

import {
  AIRCRAFT_ICON_SHAPES,
  AIRCRAFT_ICON_SVGS,
  ICON_PALETTE_NAMES,
  ICON_PALETTES,
  ICON_PIXELS,
  iconImageId,
  MLAT_RING_IMAGE_ID,
  renderIconSvg,
} from "@/features/map/aircraft/icons/silhouettes";

/** Every (shape, palette) pair the catalogue renders. */
const RENDERED = AIRCRAFT_ICON_SHAPES.flatMap((shape) =>
  ICON_PALETTE_NAMES.map((palette) => [shape, palette] as const),
);

/**
 * The path-data grammar the artwork uses. jsdom's parser only checks XML
 * well-formedness, so a stray letter in a `d` attribute — which Chromium
 * would reject, silently dropping the whole aircraft layer — needs its own
 * check. Absolute and relative moves, lines, cubics and arcs, close.
 */
const PATH_DATA = /^[MLHVCAZmlhvcaz0-9 .,-]+$/;

interface Box {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * The geometric bounding box of an icon's parts, ignoring stroke width.
 * jsdom has no `getBBox`, so this walks the path grammar the artwork uses
 * (absolute `M L H V C A`, relative `l h v c a`, close) plus rect, circle and
 * ellipse. A curve's or arc's control points are not visited — the drawings
 * only use them for rounded nose and bar ends, where the endpoints bound
 * the shape closely enough for this check.
 */
function boundingBox(root: Element): Box {
  const box: Box = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  const visit = (x: number, y: number): void => {
    box.minX = Math.min(box.minX, x);
    box.minY = Math.min(box.minY, y);
    box.maxX = Math.max(box.maxX, x);
    box.maxY = Math.max(box.maxY, y);
  };
  const attr = (el: Element, name: string): number => Number(el.getAttribute(name) ?? "0");

  for (const el of root.querySelectorAll("rect")) {
    visit(attr(el, "x"), attr(el, "y"));
    visit(attr(el, "x") + attr(el, "width"), attr(el, "y") + attr(el, "height"));
  }
  for (const el of root.querySelectorAll("circle")) {
    visit(attr(el, "cx") - attr(el, "r"), attr(el, "cy") - attr(el, "r"));
    visit(attr(el, "cx") + attr(el, "r"), attr(el, "cy") + attr(el, "r"));
  }
  for (const el of root.querySelectorAll("ellipse")) {
    visit(attr(el, "cx") - attr(el, "rx"), attr(el, "cy") - attr(el, "ry"));
    visit(attr(el, "cx") + attr(el, "rx"), attr(el, "cy") + attr(el, "ry"));
  }
  for (const el of root.querySelectorAll("path")) {
    let x = 0;
    let y = 0;
    const tokens = (el.getAttribute("d") ?? "").match(/[MLHVCAZmlhvcaz]|-?\d+(?:\.\d+)?/g) ?? [];
    let i = 0;
    while (i < tokens.length) {
      const cmd = tokens[i++] ?? "";
      const nums = (count: number): number[] => {
        const out = tokens.slice(i, i + count).map(Number);
        i += count;
        return out;
      };
      // Implicit repetition (e.g. `L1 2 3 4`) is not used by the artwork.
      switch (cmd) {
        case "M":
        case "L":
          [x, y] = nums(2) as [number, number];
          break;
        case "m":
        case "l": {
          const [dx, dy] = nums(2) as [number, number];
          x += dx;
          y += dy;
          break;
        }
        case "H":
          [x] = nums(1) as [number];
          break;
        case "h":
          x += (nums(1) as [number])[0];
          break;
        case "V":
          [y] = nums(1) as [number];
          break;
        case "v":
          y += (nums(1) as [number])[0];
          break;
        case "C": {
          const c = nums(6);
          x = c[4] ?? x;
          y = c[5] ?? y;
          break;
        }
        case "c": {
          const c = nums(6);
          x += c[4] ?? 0;
          y += c[5] ?? 0;
          break;
        }
        case "A": {
          const a = nums(7);
          x = a[5] ?? x;
          y = a[6] ?? y;
          break;
        }
        case "a": {
          const a = nums(7);
          x += a[5] ?? 0;
          y += a[6] ?? 0;
          break;
        }
        case "Z":
        case "z":
          continue;
        default:
          throw new Error(`unexpected path token ${cmd}`);
      }
      visit(x, y);
    }
  }
  return box;
}

describe("the silhouette catalogue", () => {
  it("renders twenty-one shapes in three palettes plus the MLAT ring", () => {
    expect(AIRCRAFT_ICON_SHAPES).toHaveLength(21);
    expect(ICON_PALETTE_NAMES).toEqual(["civil", "military", "government"]);
    expect(Object.keys(AIRCRAFT_ICON_SVGS)).toHaveLength(21 * 3 + 1);
    expect(AIRCRAFT_ICON_SVGS[MLAT_RING_IMAGE_ID]).toBeDefined();
  });

  it("keeps the generic fallback and the ground form slice 014 drew", () => {
    expect(AIRCRAFT_ICON_SHAPES).toContain("generic");
    expect(AIRCRAFT_ICON_SHAPES).toContain("ground");
  });

  it("gives every image a distinct namespaced id carrying its palette", () => {
    const ids = Object.keys(AIRCRAFT_ICON_SVGS);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id.startsWith("flightsite-aircraft-")).toBe(true);
      if (id !== MLAT_RING_IMAGE_ID) {
        expect(id).toMatch(/--(civil|military|government)$/);
      }
    }
    expect(iconImageId("tandem-rotor", "government")).toBe(
      "flightsite-aircraft-tandem-rotor--government",
    );
  });

  it("defaults the image id to the civil palette", () => {
    expect(iconImageId("narrowbody")).toBe(iconImageId("narrowbody", "civil"));
  });
});

describe("the silhouette artwork", () => {
  it.each(RENDERED)("%s in the %s palette is a well-formed square SVG", (shape, palette) => {
    const markup = renderIconSvg(shape, palette);
    expect(AIRCRAFT_ICON_SVGS[iconImageId(shape, palette)]).toBe(markup);

    const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
    expect(parsed.querySelector("parsererror")).toBeNull();

    const root = parsed.documentElement;
    expect(root.tagName).toBe("svg");
    expect(root.getAttribute("viewBox")).toBe(`0 0 ${ICON_PIXELS} ${ICON_PIXELS}`);
    expect(root.getAttribute("width")).toBe(String(ICON_PIXELS));
    expect(root.getAttribute("height")).toBe(String(ICON_PIXELS));
    expect(root.childElementCount).toBeGreaterThan(0);

    for (const path of parsed.querySelectorAll("path")) {
      expect(path.getAttribute("d")).toMatch(PATH_DATA);
    }
  });

  it.each([...AIRCRAFT_ICON_SHAPES])("%s takes its body colour from the palette", (shape) => {
    const civil = renderIconSvg(shape, "civil");
    const military = renderIconSvg(shape, "military");
    const government = renderIconSvg(shape, "government");

    expect(civil).toContain(ICON_PALETTES.civil.body);
    expect(military).toContain(ICON_PALETTES.military.body);
    expect(government).toContain(ICON_PALETTES.government.body);
    expect(military).not.toBe(civil);
    expect(government).not.toBe(civil);
    // The casing is shared: a tint changes the body, never the outline.
    expect(military).toContain(ICON_PALETTES.military.ink);
    expect(ICON_PALETTES.military.ink).toBe(ICON_PALETTES.civil.ink);
  });

  it.each([...AIRCRAFT_ICON_SHAPES])("%s stays inside the canvas, balanced on the anchor", (shape) => {
    // A wingtip off-canvas is clipped; a drawing off-centre renders the
    // aircraft away from its reported position, most visibly while turning.
    const parsed = new DOMParser().parseFromString(
      renderIconSvg(shape, "civil"),
      "image/svg+xml",
    );
    const box = boundingBox(parsed.documentElement);
    expect(box.minX).toBeGreaterThanOrEqual(0);
    expect(box.minY).toBeGreaterThanOrEqual(0);
    expect(box.maxX).toBeLessThanOrEqual(ICON_PIXELS);
    expect(box.maxY).toBeLessThanOrEqual(ICON_PIXELS);
    // Planforms are symmetric about the fuselage; the helicopter's tail rotor
    // sticks out one side, which is the whole of the slack allowed here.
    expect(Math.abs((box.minX + box.maxX) / 2 - ICON_PIXELS / 2)).toBeLessThanOrEqual(2.5);
    // Longer dimension big enough to survive the zoom-3 size stop.
    expect(Math.max(box.maxX - box.minX, box.maxY - box.minY)).toBeGreaterThanOrEqual(36);
  });

  it("distinguishes MLAT with a dash pattern, not only a colour", () => {
    // SPEC §36: never rely exclusively on colour.
    expect(AIRCRAFT_ICON_SVGS[MLAT_RING_IMAGE_ID]).toContain("stroke-dasharray");
  });
});
