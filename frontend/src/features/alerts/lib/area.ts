/**
 * The drawn-area condition's geometry on the client (roadmap slice 089).
 *
 * The rule builder edits an area two ways — on a mini-map, and as text (one
 * `longitude, latitude` pair per line, the keyboard-accessible fallback) —
 * and both edit the same thing: the text. The map parses it to draw, and
 * writes it back when a vertex is added or dragged, so the two can never
 * disagree about which shape the rule holds.
 *
 * Validation mirrors `backend/src/flightsite/alerts/area.py`'s
 * `normalize_ring` rule for rule, in the same order and with the same
 * bounds, so a shape the builder accepts is one the API accepts (the
 * backend stays authoritative and its own refusal is still shown). A ring
 * is 3–64 distinct vertices in `[longitude, latitude]` order — GeoJSON's,
 * which is also MapLibre's — closed or auto-closed, with no edge crossing
 * the antimeridian, no two edges crossing, and some area inside.
 */

/** `[longitude, latitude]`, decimal degrees. */
export type Vertex = [number, number];

/** Bounds on a ring's distinct vertices — `MIN_AREA_VERTICES` /
 * `MAX_AREA_VERTICES` in `alerts/area.py`. */
export const MIN_AREA_VERTICES = 3;
export const MAX_AREA_VERTICES = 64;

/** Decimal places a map click is rounded to: about a metre, which keeps the
 * text fallback readable without moving a vertex anywhere a user would see. */
export const VERTEX_DECIMALS = 5;

/** A coordinate rounded for display and storage. */
export function roundCoordinate(value: number): number {
  const factor = 10 ** VERTEX_DECIMALS;
  return Math.round(value * factor) / factor;
}

/** One vertex per line, `lon, lat`. */
export function formatAreaText(vertices: readonly Vertex[]): string {
  return vertices.map(([lon, lat]) => `${lon}, ${lat}`).join("\n");
}

export type ParsedArea =
  { ok: true; vertices: Vertex[] } | { ok: false; error: string };

/**
 * The vertices `text` describes, or the first line that is not a pair.
 *
 * Blank lines are ignored. Separators may be a comma, whitespace, or both,
 * so a pair pasted from a spreadsheet or from GeoJSON with its brackets
 * stripped reads the same. A last vertex repeating the first is the
 * closed-ring spelling and is dropped, exactly as the backend does.
 */
export function parseAreaText(text: string): ParsedArea {
  const vertices: Vertex[] = [];
  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = (lines[index] ?? "").trim().replace(/^\[|\]$/g, "");
    if (line.length === 0) {
      continue;
    }
    const parts = line.split(/[\s,]+/).filter((part) => part.length > 0);
    const numbers = parts.map(Number);
    const [lon, lat] = numbers;
    if (
      numbers.length !== 2 ||
      lon === undefined ||
      lat === undefined ||
      !numbers.every(Number.isFinite)
    ) {
      return {
        ok: false,
        error: `Line ${index + 1} is not a "longitude, latitude" pair.`,
      };
    }
    vertices.push([lon, lat]);
  }
  const first = vertices[0];
  const last = vertices.at(-1);
  if (
    vertices.length >= 2 &&
    first !== undefined &&
    last !== undefined &&
    first[0] === last[0] &&
    first[1] === last[1]
  ) {
    vertices.pop();
  }
  return { ok: true, vertices };
}

/**
 * Every line of `text` that reads as a pair, skipping the ones that do not —
 * what the mini-map draws while the user is half-way through typing a line.
 * Validation never uses this: a line that is not a pair is an error there.
 */
export function readableVertices(text: string): Vertex[] {
  const readable = text.split(/\r?\n/).flatMap((line): Vertex[] => {
    const parsed = parseAreaText(line);
    return parsed.ok ? parsed.vertices : [];
  });
  // Drop a closing repeat exactly as `parseAreaText` does.
  const reparsed = parseAreaText(formatAreaText(readable));
  return reparsed.ok ? reparsed.vertices : readable;
}

function orientation(a: Vertex, b: Vertex, c: Vertex): number {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function withinBox(a: Vertex, b: Vertex, p: Vertex): boolean {
  return (
    Math.min(a[0], b[0]) <= p[0] &&
    p[0] <= Math.max(a[0], b[0]) &&
    Math.min(a[1], b[1]) <= p[1] &&
    p[1] <= Math.max(a[1], b[1])
  );
}

function segmentsIntersect(
  a: Vertex,
  b: Vertex,
  c: Vertex,
  d: Vertex,
): boolean {
  const o1 = orientation(a, b, c);
  const o2 = orientation(a, b, d);
  const o3 = orientation(c, d, a);
  const o4 = orientation(c, d, b);
  if (o1 * o2 < 0 && o3 * o4 < 0) {
    return true;
  }
  return (
    (o1 === 0 && withinBox(a, b, c)) ||
    (o2 === 0 && withinBox(a, b, d)) ||
    (o3 === 0 && withinBox(c, d, a)) ||
    (o4 === 0 && withinBox(c, d, b))
  );
}

/** What is wrong with a ring of vertices, or `null` when the API will
 * accept it. The order and wording follow the backend's own checks. */
export function validateAreaVertices(
  vertices: readonly Vertex[],
): string | null {
  const count = vertices.length;
  if (count < MIN_AREA_VERTICES || count > MAX_AREA_VERTICES) {
    return `An area needs between ${MIN_AREA_VERTICES} and ${MAX_AREA_VERTICES} vertices (it has ${count}).`;
  }
  for (const [index, [lon, lat]] of vertices.entries()) {
    if (lon < -180 || lon > 180) {
      return `Vertex ${index + 1} has longitude ${lon}, outside -180 to 180. Pairs are longitude first.`;
    }
    if (lat < -90 || lat > 90) {
      return `Vertex ${index + 1} has latitude ${lat}, outside -90 to 90. Pairs are longitude first.`;
    }
  }
  const keys = new Set(vertices.map(([lon, lat]) => `${lon},${lat}`));
  if (keys.size !== count) {
    return "Each vertex must be different: one is repeated.";
  }
  const edges: [Vertex, Vertex][] = vertices.map((vertex, index) => [
    vertex,
    vertices[(index + 1) % count] as Vertex,
  ]);
  if (edges.some(([a, b]) => Math.abs(b[0] - a[0]) > 180)) {
    return "An area cannot cross the 180° meridian. Draw one rule on each side.";
  }
  for (let i = 0; i < count; i += 1) {
    const [a, b] = edges[i] as [Vertex, Vertex];
    const after = (edges[(i + 1) % count] as [Vertex, Vertex])[1];
    const dot =
      (b[0] - a[0]) * (after[0] - b[0]) + (b[1] - a[1]) * (after[1] - b[1]);
    if (orientation(a, b, after) === 0 && dot < 0) {
      return `The edges cannot cross: the edge at vertex ${i + 2} folds back on itself.`;
    }
    for (let j = i + 2; j < count; j += 1) {
      if (i === 0 && j === count - 1) {
        continue;
      }
      const [c, d] = edges[j] as [Vertex, Vertex];
      if (segmentsIntersect(a, b, c, d)) {
        return `The edges cannot cross: edge ${i + 1} crosses edge ${j + 1}.`;
      }
    }
  }
  const doubledArea = edges.reduce(
    (sum, [a, b]) => sum + a[0] * b[1] - b[0] * a[1],
    0,
  );
  if (Math.abs(doubledArea) <= 1e-18) {
    return "The vertices are in a line, so the area encloses nothing.";
  }
  return null;
}

/** The mini-map's drawing: the shape and its vertices as two feature
 * collections. Two vertices draw as a line (the shape so far); three or more
 * as a closed polygon. Each vertex carries its `index` for drag hit-tests. */
export function buildAreaGeojson(vertices: readonly Vertex[]): {
  shape: GeoJSON.FeatureCollection;
  points: GeoJSON.FeatureCollection;
} {
  const features: GeoJSON.Feature[] = [];
  const first = vertices[0];
  if (vertices.length >= 3 && first) {
    features.push({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [[...vertices, first]] },
    });
  } else if (vertices.length === 2) {
    features.push({
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: [...vertices] },
    });
  }
  return {
    shape: { type: "FeatureCollection", features },
    points: {
      type: "FeatureCollection",
      features: vertices.map((vertex, index) => ({
        type: "Feature",
        properties: { index },
        geometry: { type: "Point", coordinates: vertex },
      })),
    },
  };
}

/** The GeoJSON ring the API stores: the vertices, closed. */
export function closedRing(vertices: readonly Vertex[]): Vertex[] {
  const first = vertices[0];
  return first === undefined ? [] : [...vertices, first];
}
