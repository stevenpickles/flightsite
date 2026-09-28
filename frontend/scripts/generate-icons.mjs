#!/usr/bin/env node
/**
 * Rasterizes FlightSite's brand mark (`public/favicon.svg`) into the PNG
 * icons the web app manifest and iOS home screen need (roadmap slice 084,
 * issue #227). Run by hand — `npm run icons` — whenever the mark changes;
 * the PNGs it writes to `public/icons/` are committed, so neither the build
 * nor the Docker image depends on this script.
 *
 * No dependency: the mark is five circles and one radar-sweep sector, so it
 * is drawn here analytically — each pixel is supersampled on a 4 x 4 grid,
 * every shape is tested geometrically in the SVG's own 32 x 32 user space,
 * and the samples are composited in document order exactly as the SVG
 * paints them — then encoded with Node's own `zlib`. The shape list below
 * mirrors `favicon.svg` element for element; keep the two in step.
 *
 * Outputs:
 *
 * - `icon-192.png`, `icon-512.png` — `purpose: "any"`: the mark edge to
 *   edge on a transparent canvas, exactly as the favicon draws it.
 * - `icon-maskable-192.png`, `icon-maskable-512.png` — `purpose:
 *   "maskable"`: the mark scaled into the central 80 % safe zone on an
 *   opaque background, so any launcher mask shape crops only background.
 * - `apple-touch-icon.png` (180 x 180) — iOS fills transparency with black
 *   and applies its own rounded mask, so this is the maskable layout too.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(__dirname, "..", "public", "icons");

/** The mark's own background (`favicon.svg`'s outer circle fill), reused as
 * the opaque canvas of the maskable and Apple icons. */
const BACKGROUND = hex("#020617");
const TEAL = hex("#5EEAD4");
const CYAN_DARK = hex("#164E63");

function hex(value) {
  const n = Number.parseInt(value.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// ---- Geometry (SVG user space, viewBox 0 0 32 32) --------------------------

const CX = 16;
const CY = 16;

/** Circle through (16,2) and (27.5,9) with r = 14 — the sweep path's arc
 * (`A14 14 0 0 1 27.5 9`: small arc, clockwise). */
const ARC = (() => {
  const [x1, y1, x2, y2, r] = [16, 2, 27.5, 9, 14];
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const chord = Math.hypot(dx, dy);
  const h = Math.sqrt(r * r - (chord / 2) ** 2);
  // Clockwise sweep in SVG's y-down space with the small arc puts the
  // centre on the right-hand side of the chord's direction.
  const ux = -dy / chord;
  const uy = dx / chord;
  const candidates = [
    [mx + ux * h, my + uy * h],
    [mx - ux * h, my - uy * h],
  ];
  // Of the two, the centre that makes (x1,y1)->(x2,y2) a clockwise small
  // arc is the one with a positive cross product (y-down coordinates).
  const [cx, cy] =
    candidates.find(([cx, cy]) => {
      const cross = (x1 - cx) * (y2 - cy) - (y1 - cy) * (x2 - cx);
      return cross > 0;
    }) ?? candidates[0];
  return { x1, y1, x2, y2, r, cx, cy };
})();

function side(ax, ay, bx, by, px, py) {
  return (bx - ax) * (py - ay) - (by - ay) * (px - ax);
}

function inTriangle(px, py, ax, ay, bx, by, cx, cy) {
  const d1 = side(ax, ay, bx, by, px, py);
  const d2 = side(bx, by, cx, cy, px, py);
  const d3 = side(cx, cy, ax, ay, px, py);
  const neg = d1 < 0 || d2 < 0 || d3 < 0;
  const pos = d1 > 0 || d2 > 0 || d3 > 0;
  return !(neg && pos);
}

/** `M16 16 L16 2 A14 14 0 0 1 27.5 9 Z`: the triangle from the centre to
 * the arc's two ends, plus the circular segment between chord and arc. */
function inSweep(px, py) {
  const { x1, y1, x2, y2, r, cx, cy } = ARC;
  if (inTriangle(px, py, CX, CY, x1, y1, x2, y2)) {
    return true;
  }
  const inArcDisk = Math.hypot(px - cx, py - cy) <= r;
  const pointSide = side(x1, y1, x2, y2, px, py);
  const centreSide = side(x1, y1, x2, y2, cx, cy);
  return inArcDisk && Math.sign(pointSide) !== Math.sign(centreSide);
}

function ring(d, r, width) {
  return Math.abs(d - r) <= width / 2;
}

/** The colour and opacity each shape paints at (x, y), in document order;
 * `null` where it paints nothing. */
const LAYERS = [
  (x, y, d) => (d <= 15 ? [BACKGROUND, 1] : null), // outer circle fill
  (x, y, d) => (ring(d, 15, 1.5) ? [TEAL, 1] : null), // outer circle stroke
  (x, y, d) => (ring(d, 10, 1) ? [CYAN_DARK, 1] : null),
  (x, y, d) => (ring(d, 5, 1) ? [CYAN_DARK, 1] : null),
  (x, y) => (inSweep(x, y) ? [TEAL, 0.25] : null),
  (x, y, d) => (d <= 1.4 ? [TEAL, 1] : null), // centre dot
];

/** Source-over composite of one sample, starting from `base` (RGBA 0..1). */
function paintSample(x, y, base) {
  let [r, g, b, a] = base;
  const d = Math.hypot(x - CX, y - CY);
  for (const layer of LAYERS) {
    const hit = layer(x, y, d);
    if (hit === null) {
      continue;
    }
    const [[sr, sg, sb], sa] = hit;
    const outA = sa + a * (1 - sa);
    r = (sr / 255) * sa + r * a * (1 - sa);
    g = (sg / 255) * sa + g * a * (1 - sa);
    b = (sb / 255) * sa + b * a * (1 - sa);
    r /= outA;
    g /= outA;
    b /= outA;
    a = outA;
  }
  return [r, g, b, a];
}

const SUPERSAMPLE = 4;

/**
 * Renders a `size` x `size` RGBA buffer. `markFraction` is how much of the
 * canvas the mark's 31.5-unit outer diameter spans; `opaque` fills the
 * canvas with the background first.
 */
function render(size, markFraction, opaque) {
  const pixels = Buffer.alloc(size * size * 4);
  const unitsPerPixel = 31.5 / (size * markFraction);
  const base = opaque ? [...BACKGROUND.map((c) => c / 255), 1] : [0, 0, 0, 0];
  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      let [r, g, b, a] = [0, 0, 0, 0];
      for (let sy = 0; sy < SUPERSAMPLE; sy += 1) {
        for (let sx = 0; sx < SUPERSAMPLE; sx += 1) {
          const x =
            CX + (px + (sx + 0.5) / SUPERSAMPLE - size / 2) * unitsPerPixel;
          const y =
            CY + (py + (sy + 0.5) / SUPERSAMPLE - size / 2) * unitsPerPixel;
          const [sr, sg, sb, sa] = paintSample(x, y, base);
          // Premultiplied accumulation, so edge pixels average correctly.
          r += sr * sa;
          g += sg * sa;
          b += sb * sa;
          a += sa;
        }
      }
      const n = SUPERSAMPLE * SUPERSAMPLE;
      const offset = (py * size + px) * 4;
      const alpha = a / n;
      pixels[offset] = alpha > 0 ? Math.round((r / a) * 255) : 0;
      pixels[offset + 1] = alpha > 0 ? Math.round((g / a) * 255) : 0;
      pixels[offset + 2] = alpha > 0 ? Math.round((b / a) * 255) : 0;
      pixels[offset + 3] = Math.round(alpha * 255);
    }
  }
  return pixels;
}

// ---- PNG encoding -----------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) {
    c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function encodePng(size, pixels) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // colour type: RGBA
  header[10] = 0; // compression
  header[11] = 0; // filter
  header[12] = 0; // interlace
  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y += 1) {
    raw[y * (stride + 1)] = 0; // filter type: none
    pixels.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ---- Outputs ------------------------------------------------------------------

/** Maskable safe zone: a centred circle of 40 % radius, so the mark's
 * diameter may span at most 80 % of the canvas. */
const MASKABLE_FRACTION = 0.8;

const OUTPUTS = [
  { file: "icon-192.png", size: 192, fraction: 1, opaque: false },
  { file: "icon-512.png", size: 512, fraction: 1, opaque: false },
  {
    file: "icon-maskable-192.png",
    size: 192,
    fraction: MASKABLE_FRACTION,
    opaque: true,
  },
  {
    file: "icon-maskable-512.png",
    size: 512,
    fraction: MASKABLE_FRACTION,
    opaque: true,
  },
  {
    file: "apple-touch-icon.png",
    size: 180,
    fraction: MASKABLE_FRACTION,
    opaque: true,
  },
];

mkdirSync(outDir, { recursive: true });
for (const { file, size, fraction, opaque } of OUTPUTS) {
  const png = encodePng(size, render(size, fraction, opaque));
  writeFileSync(path.join(outDir, file), png);
  console.log(`[generate-icons] wrote public/icons/${file} (${png.length} B)`);
}
