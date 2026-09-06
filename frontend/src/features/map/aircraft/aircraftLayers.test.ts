import {
  createPropertyExpression,
  isExpression,
  latest,
  validateStyleMin,
} from "@maplibre/maplibre-gl-style-spec";
import type {
  StylePropertySpecification,
  StyleSpecification,
} from "@maplibre/maplibre-gl-style-spec";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AIRCRAFT_ATTENTION_LAYER_ID,
  AIRCRAFT_LABEL_LAYER_ID,
  AIRCRAFT_MLAT_RING_LAYER_ID,
  AIRCRAFT_SELECTED_LABEL_LAYER_ID,
  AIRCRAFT_SELECTION_LAYER_ID,
  AIRCRAFT_SOURCE_ID,
  AIRCRAFT_SYMBOL_LAYER_ID,
  AIRCRAFT_TRACK_LAYER_ID,
  AIRCRAFT_TRACK_SOURCE_ID,
  aircraftIcaoAtPoint,
  ensureAircraftLayers,
  setAircraftData,
  setTrackData,
} from "@/features/map/aircraft/aircraftLayers";
import { drawAircraftFrame } from "@/features/map/aircraft/frame";
import { MLAT_RING_IMAGE_ID } from "@/features/map/aircraft/icons/silhouettes";
import { OPENFREEMAP_GLYPHS_URL } from "@/features/map/basemaps/paletteStyleFactory";
import {
  SORT_KEY_DEFAULT,
  SORT_KEY_INTERESTING,
} from "@/features/map/labels/priority";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import { MapLibreMockMap } from "@/test/maplibreGlMock";

const NOW = 1_800_000_000_000;

let mock: MapLibreMockMap;
let map: MapLibreGlMap;

const EMPTY_COLLECTION = {
  type: "FeatureCollection" as const,
  features: [],
};

beforeEach(() => {
  mock = new MapLibreMockMap({});
  map = mock as unknown as MapLibreGlMap;
});

describe("ensureAircraftLayers", () => {
  it("adds both sources and all seven layers", () => {
    ensureAircraftLayers(map);
    expect([...mock.sources.keys()].sort()).toEqual(
      [AIRCRAFT_SOURCE_ID, AIRCRAFT_TRACK_SOURCE_ID].sort(),
    );
    expect([...mock.layers.keys()]).toEqual([
      AIRCRAFT_TRACK_LAYER_ID,
      AIRCRAFT_ATTENTION_LAYER_ID,
      AIRCRAFT_SELECTION_LAYER_ID,
      AIRCRAFT_MLAT_RING_LAYER_ID,
      AIRCRAFT_SYMBOL_LAYER_ID,
      AIRCRAFT_LABEL_LAYER_ID,
      AIRCRAFT_SELECTED_LABEL_LAYER_ID,
    ]);
  });

  it("draws the track under the icons, the rings under the symbols, and the labels above everything", () => {
    // Layer order is paint order: the selection halo and the MLAT ring are
    // decoration behind the silhouette, not on top of it, and labels must
    // paint over the silhouettes they annotate.
    ensureAircraftLayers(map);
    const order = [...mock.layers.keys()];
    expect(order.indexOf(AIRCRAFT_TRACK_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_ATTENTION_LAYER_ID),
    );
    // The attention ring is the outermost of the three rings, so it paints
    // first and the selection halo stays legible on top of it.
    expect(order.indexOf(AIRCRAFT_ATTENTION_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SELECTION_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_MLAT_RING_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SYMBOL_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_SYMBOL_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_LABEL_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_LABEL_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SELECTED_LABEL_LAYER_ID),
    );
  });

  it("is idempotent and never re-adds a layer", () => {
    ensureAircraftLayers(map);
    const first = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID);
    ensureAircraftLayers(map);
    expect(mock.layers.size).toBe(7);
    expect(mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)).toBe(first);
  });

  it("never introduces a clustered GeoJSON source", () => {
    // Roadmap slice 015 explicitly rules out marker clustering as a
    // decluttering mechanism — this guards against one creeping in later.
    const addSource = vi.spyOn(mock, "addSource");
    ensureAircraftLayers(map);
    expect(addSource).toHaveBeenCalled();
    for (const call of addSource.mock.calls) {
      const options = call[1] as Record<string, unknown> | undefined;
      expect(options?.cluster).toBeUndefined();
    }
  });

  it("draws the attention ring only for aircraft with an active match", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_ATTENTION_LAYER_ID)?.filter).toEqual([
      "!=",
      ["get", "severity"],
      "",
    ]);
  });

  it("encodes severity in ring geometry, not colour alone", () => {
    // SPEC §36: "never rely exclusively on color to communicate
    // classification or severity". Radius and stroke width must both step
    // monotonically with severity, so the ladder survives a viewer who
    // cannot separate amber from red.
    ensureAircraftLayers(map);
    const paint = mock.layers.get(AIRCRAFT_ATTENTION_LAYER_ID)?.paint as Record<
      string,
      unknown
    >;

    const pick = (expression: unknown[], severity: string): number => {
      const index = expression.indexOf(severity);
      return index === -1
        ? (expression.at(-1) as number)
        : (expression[index + 1] as number);
    };

    const width = paint["circle-stroke-width"] as unknown[];
    expect(pick(width, "info")).toBeLessThan(pick(width, "interesting"));
    expect(pick(width, "interesting")).toBeLessThan(pick(width, "high"));
    expect(pick(width, "high")).toBeLessThan(pick(width, "critical"));

    // The radius folds severity into each zoom stop's output — the same
    // shape ICON_SIZE uses, because `["zoom"]` must stay the direct input
    // of the top-level interpolate or style validation fails silently.
    const radius = paint["circle-radius"] as unknown[];
    expect(radius[0]).toBe("interpolate");
    expect(radius[2]).toEqual(["zoom"]);

    // Read the selection halo's own radius rather than restating its
    // numbers, so this stays true if that layer is ever retuned.
    const halo = (
      mock.layers.get(AIRCRAFT_SELECTION_LAYER_ID)?.paint as Record<
        string,
        unknown
      >
    )["circle-radius"] as unknown[];

    for (const [stopIndex, haloIndex] of [
      [4, 4],
      [6, 6],
    ]) {
      const stop = radius[stopIndex!] as unknown[];
      expect(stop[0]).toBe("match");
      expect(pick(stop, "info")).toBeLessThan(pick(stop, "interesting"));
      expect(pick(stop, "interesting")).toBeLessThan(pick(stop, "high"));
      expect(pick(stop, "high")).toBeLessThan(pick(stop, "critical"));
      // Outside the selection halo at the same zoom, so a selected alerting
      // aircraft shows both rings rather than one swallowing the other.
      expect(pick(stop, "info")).toBeGreaterThan(halo[haloIndex!] as number);
    }
  });

  it("fades the attention ring with the feature's own opacity", () => {
    // A stale or ground-dimmed aircraft's ring must fade exactly as its icon
    // does, rather than staying at full strength over a ghost.
    ensureAircraftLayers(map);
    const paint = mock.layers.get(AIRCRAFT_ATTENTION_LAYER_ID)?.paint as Record<
      string,
      unknown
    >;
    expect(paint["circle-stroke-opacity"]).toEqual(["get", "opacity"]);
    const fill = paint["circle-opacity"] as unknown[];
    expect(fill[0]).toBe("*");
    expect(fill[1]).toEqual(["get", "opacity"]);
  });

  it("filters the non-selected label layer to non-empty, non-selected labels", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.filter).toEqual([
      "all",
      ["!=", ["get", "label"], ""],
      ["==", ["get", "selected"], false],
    ]);
  });

  it("filters the selected label layer to the selected feature", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_SELECTED_LABEL_LAYER_ID)?.filter).toEqual([
      "==",
      ["get", "selected"],
      true,
    ]);
  });

  it("disables collision overlap for ordinary labels but not for the selected one", () => {
    // The whole point of the split: MapLibre's collision system can hide an
    // ordinary label, but the selected aircraft's label must never be the
    // one that loses that contest.
    ensureAircraftLayers(map);
    const ordinary = mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    const selected = mock.layers.get(AIRCRAFT_SELECTED_LABEL_LAYER_ID)
      ?.layout as Record<string, unknown>;
    expect(ordinary["text-allow-overlap"]).toBe(false);
    expect(selected["text-allow-overlap"]).toBe(true);
    expect(selected["text-ignore-placement"]).toBe(true);
  });

  it("lets an ordinary label try other placements before it is hidden", () => {
    // Issue #143's second mechanism: with one fixed anchor, a label that
    // loses the collision contest blinks out entirely. Variable anchoring
    // makes hiding the last resort rather than the first response.
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    const anchors = layout["text-variable-anchor"] as string[];
    expect(anchors.length).toBeGreaterThan(1);
    // "top" first keeps the uncontested placement exactly where it was.
    expect(anchors[0]).toBe("top");
    expect(new Set(anchors).size).toBe(anchors.length);
    // MapLibre ignores both of these once text-variable-anchor is set, so
    // leaving either behind would be dead configuration that reads as if it
    // still placed the label.
    expect(layout["text-anchor"]).toBeUndefined();
    expect(layout["text-offset"]).toBeUndefined();
    expect(layout["text-radial-offset"]).toEqual(expect.any(Number));
    // Justification has to follow the anchor that won. At MapLibre's default
    // of "center", a multi-line label relocated to the left or right anchor
    // stays centre-justified and turns a ragged edge toward its own aircraft.
    expect(layout["text-justify"]).toBe("auto");
  });

  it("keeps every candidate placement the anchor-thrash decision was measured against", () => {
    // Issue #147 accepted the residual anchor movement undamped, and the
    // measurement behind that rests on this exact list: four candidates so a
    // contested label has somewhere to go (issue #143's fix), in an order
    // where the first is the placement an uncontested label already had.
    // Trimming the list is one of the dampers that decision rejected, so it
    // is pinned here rather than left to a later "tidy-up".
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    expect(layout["text-variable-anchor"]).toEqual([
      "top",
      "bottom",
      "right",
      "left",
    ]);
  });

  it("keeps the selected label on a fixed anchor, never a variable one", () => {
    // The selected label must not wander around its aircraft either — the
    // fixed pair is what pins it under the icon, and it can never collide
    // away, so it has nothing to relocate for.
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_SELECTED_LABEL_LAYER_ID)
      ?.layout as Record<string, unknown>;
    expect(layout["text-variable-anchor"]).toBeUndefined();
    expect(layout["text-radial-offset"]).toBeUndefined();
    expect(layout["text-anchor"]).toBe("top");
    expect(layout["text-offset"]).toEqual([0, 1]);
    // "auto" justification only means anything under variable anchoring, and
    // this layer has none — so it stays off rather than riding along.
    expect(layout["text-justify"]).toBeUndefined();
  });

  it("prioritizes interesting aircraft over ordinary ones in the label collision order", () => {
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    expect(layout["symbol-sort-key"]).toEqual([
      "case",
      ["get", "interesting"],
      SORT_KEY_INTERESTING,
      SORT_KEY_DEFAULT,
    ]);
  });

  it("reads label text from the precomputed feature property, never composing it in the style", () => {
    ensureAircraftLayers(map);
    for (const id of [
      AIRCRAFT_LABEL_LAYER_ID,
      AIRCRAFT_SELECTED_LABEL_LAYER_ID,
    ]) {
      const layout = mock.layers.get(id)?.layout as Record<string, unknown>;
      expect(layout["text-field"]).toEqual(["get", "label"]);
    }
  });

  it("fades label opacity with the same staleness signal as the icon", () => {
    ensureAircraftLayers(map);
    for (const id of [
      AIRCRAFT_LABEL_LAYER_ID,
      AIRCRAFT_SELECTED_LABEL_LAYER_ID,
    ]) {
      const paint = mock.layers.get(id)?.paint as Record<string, unknown>;
      expect(paint["text-opacity"]).toEqual(["get", "opacity"]);
    }
  });

  it("updates an existing source in place rather than replacing it", () => {
    // Re-adding the source every frame would rebuild the style and defeat the
    // whole point of setData.
    ensureAircraftLayers(map);
    const source = mock.getSource(AIRCRAFT_SOURCE_ID);
    ensureAircraftLayers(map);
    expect(mock.getSource(AIRCRAFT_SOURCE_ID)).toBe(source);
    expect(source?.setData).toHaveBeenCalledTimes(1);
  });

  it("rotates the symbols by the feature's track, aligned to the map", () => {
    ensureAircraftLayers(map);
    const layer = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID);
    const layout = layer?.layout as Record<string, unknown>;
    expect(layout["icon-rotate"]).toEqual(["get", "track"]);
    expect(layout["icon-rotation-alignment"]).toBe("map");
    expect(layout["icon-image"]).toEqual(["get", "icon"]);
  });

  it("scales the icons with zoom and enlarges the selection", () => {
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    expect(JSON.stringify(layout["icon-size"])).toContain('["zoom"]');
    expect(JSON.stringify(layout["icon-size"])).toContain('"selected"');
  });

  it("drives icon opacity from the computed feature property", () => {
    ensureAircraftLayers(map);
    const paint = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)?.paint as Record<
      string,
      unknown
    >;
    expect(paint["icon-opacity"]).toEqual(["get", "opacity"]);
  });

  it("filters the MLAT ring to multilaterated positions and keeps it upright", () => {
    ensureAircraftLayers(map);
    const layer = mock.layers.get(AIRCRAFT_MLAT_RING_LAYER_ID);
    expect(layer?.filter).toEqual(["==", ["get", "mlat"], true]);
    const layout = layer?.layout as Record<string, unknown>;
    expect(layout["icon-image"]).toBe(MLAT_RING_IMAGE_ID);
    expect(layout["icon-rotation-alignment"]).toBe("viewport");
  });

  it("filters the selection halo to the selected feature", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_SELECTION_LAYER_ID)?.filter).toEqual([
      "==",
      ["get", "selected"],
      true,
    ]);
  });
});

describe("setAircraftData / setTrackData", () => {
  it("pushes data through the existing sources", () => {
    ensureAircraftLayers(map);
    setAircraftData(map, EMPTY_COLLECTION);
    setTrackData(map, EMPTY_COLLECTION);
    expect(mock.getSource(AIRCRAFT_SOURCE_ID)?.setData).toHaveBeenCalledWith(
      EMPTY_COLLECTION,
    );
    expect(
      mock.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.setData,
    ).toHaveBeenCalledWith(EMPTY_COLLECTION);
  });

  it("is a no-op before the layers exist", () => {
    // A frame can be scheduled between a style swap and the re-attach.
    expect(() => {
      setAircraftData(map, EMPTY_COLLECTION);
      setTrackData(map, EMPTY_COLLECTION);
    }).not.toThrow();
  });
});

describe("drawAircraftFrame", () => {
  const state = {
    aircraft: {
      aaaaaa: {
        aircraft: makeAircraft({
          icao: "aaaaaa",
          position: { lat: 47, lon: -122 },
          ground_speed_kt: null,
        }),
        receivedAt: NOW,
        positionChangedAt: NOW,
      },
    },
    departing: {},
    selectedIcao: "aaaaaa",
    track: {
      icao: "aaaaaa",
      points: [
        { lat: 47, lon: -122, at: NOW - 1000 },
        { lat: 47.1, lon: -122, at: NOW },
      ],
    },
  };

  beforeEach(() => {
    ensureAircraftLayers(map);
  });

  it("rebuilds the aircraft source from store state", () => {
    drawAircraftFrame(map, state, NOW);
    const data = mock.getSource(AIRCRAFT_SOURCE_ID)?.data as {
      features: { properties: { icao: string; selected: boolean } }[];
    };
    expect(data.features).toHaveLength(1);
    expect(data.features[0]?.properties).toMatchObject({
      icao: "aaaaaa",
      selected: true,
    });
  });

  it("fully labels the selected aircraft at the mock map's default zoom", () => {
    // The mock defaults `getZoom()` into the full-label band precisely so a
    // test like this one exercises the real `frame.ts` -> `geojson.ts` path
    // end to end instead of stubbing zoom away.
    drawAircraftFrame(map, state, NOW);
    const data = mock.getSource(AIRCRAFT_SOURCE_ID)?.data as {
      features: { properties: { label: string } }[];
    };
    expect(data.features[0]?.properties.label).toBe("RCH471\nFL310");
  });

  it("leaves the track alone on an interpolation frame", () => {
    // Re-serializing up to 900 coordinates ten times a second for an unchanged
    // line is exactly the per-frame waste a Pi cannot afford.
    const track = mock.getSource(AIRCRAFT_TRACK_SOURCE_ID);
    drawAircraftFrame(map, state, NOW);
    expect(track?.setData).not.toHaveBeenCalled();
  });

  it("rebuilds the track when asked", () => {
    drawAircraftFrame(map, state, NOW, { includeTrack: true });
    const data = mock.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.data as {
      features: unknown[];
    };
    expect(data.features).toHaveLength(1);
  });
});

describe("aircraftIcaoAtPoint", () => {
  it("returns the icao of the aircraft under the cursor", () => {
    ensureAircraftLayers(map);
    mock.renderedFeatures = [{ properties: { icao: "ae1463" } }];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBe("ae1463");
  });

  it("returns null when the click hit empty map", () => {
    ensureAircraftLayers(map);
    mock.renderedFeatures = [];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBeNull();
  });

  it("returns null when the layer is not on the style yet", () => {
    mock.renderedFeatures = [{ properties: { icao: "ae1463" } }];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBeNull();
  });

  it("ignores a feature with no usable icao", () => {
    ensureAircraftLayers(map);
    mock.renderedFeatures = [{ properties: { icao: 7 } }];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBeNull();
  });
});

describe("style-spec validation", () => {
  // Issue #96. `aircraftLayers.ts` warns in two places that an invalid style
  // expression fails *silently*: MapLibre fires an `error` event rather than
  // throwing, so a bad `interpolate` means the layer is never added and no
  // aircraft render — and every other test in this file mocks MapLibre away,
  // so none of them would notice. These tests run the real style spec
  // (`@maplibre/maplibre-gl-style-spec`, the same package and version
  // `maplibre-gl` itself depends on) over the layers `ensureAircraftLayers`
  // actually adds, including the label and attention layers.

  /** The spec entry for one paint/layout property of one layer type, e.g.
   * `latest.paint_circle["circle-radius"]`. */
  function propertySpec(
    layerType: string,
    group: "paint" | "layout",
    key: string,
  ): StylePropertySpecification | undefined {
    const table = (
      latest as unknown as Record<
        string,
        Record<string, StylePropertySpecification> | undefined
      >
    )[`${group}_${layerType}`];
    return table?.[key];
  }

  /**
   * A property value in the shape `createPropertyExpression` parses.
   *
   * Array-valued *constants* — `text-offset: [0, 1]`,
   * `text-variable-anchor: ["top", ...]` — are perfectly legal style values,
   * but an array is an expression as far as the parser is concerned, so it
   * reads `["top", ...]` as a call to an operator named "top". MapLibre's own
   * `normalizePropertyExpression` makes the same distinction with the same
   * `isExpression` test before handing a value to the parser; wrapping the
   * constant in `["literal", …]` is how that reaches `createPropertyExpression`
   * as what it is.
   */
  function asExpression(value: unknown): unknown {
    return Array.isArray(value) && !isExpression(value)
      ? ["literal", value]
      : value;
  }

  /** Every paint and layout property on every layer currently on the style. */
  function styleProperties(): {
    layerId: string;
    layerType: string;
    group: "paint" | "layout";
    key: string;
    value: unknown;
  }[] {
    const out: {
      layerId: string;
      layerType: string;
      group: "paint" | "layout";
      key: string;
      value: unknown;
    }[] = [];
    for (const [layerId, layer] of mock.layers) {
      for (const group of ["paint", "layout"] as const) {
        const properties = (layer[group] ?? {}) as Record<string, unknown>;
        for (const [key, value] of Object.entries(properties)) {
          out.push({
            layerId,
            layerType: layer.type as string,
            group,
            key,
            value,
          });
        }
      }
    }
    return out;
  }

  /** The layers, wrapped in the smallest style the validator will accept: the
   * GeoJSON sources they read and the glyph endpoint the real basemaps ship,
   * without which a `text-field` is itself a validation error. */
  function styleForValidation(): StyleSpecification {
    return {
      version: 8,
      glyphs: OPENFREEMAP_GLYPHS_URL,
      sources: Object.fromEntries(
        [...mock.sources.keys()].map((id) => [
          id,
          { type: "geojson", data: EMPTY_COLLECTION },
        ]),
      ),
      layers: [...mock.layers.values()],
    } as unknown as StyleSpecification;
  }

  it("parses every paint and layout property against its spec definition", () => {
    ensureAircraftLayers(map);
    const properties = styleProperties();

    const failures: string[] = [];
    const checkedByLayer = new Map<string, number>();
    for (const { layerId, layerType, group, key, value } of properties) {
      const spec = propertySpec(layerType, group, key);
      if (!spec) {
        failures.push(
          `${layerId}: ${group}.${key} is not a ${layerType} layer property`,
        );
        continue;
      }
      const parsed = createPropertyExpression(asExpression(value), key, spec);
      if (parsed.result === "error") {
        failures.push(
          `${layerId}: ${group}.${key}: ${parsed.value
            .map((error) => error.message)
            .join("; ")}`,
        );
      }
      checkedByLayer.set(layerId, (checkedByLayer.get(layerId) ?? 0) + 1);
    }

    expect(failures).toEqual([]);
    // Every layer must actually have been exercised: a layer whose paint and
    // layout were both somehow missed would make the assertion above pass
    // vacuously.
    expect([...checkedByLayer.keys()].sort()).toEqual(
      [...mock.layers.keys()].sort(),
    );
    expect(properties).not.toHaveLength(0);
  });

  it("validates the whole aircraft style, filters included, with zero errors", () => {
    // Broader than the per-property parse: this also checks the layer
    // `filter`s, the source references, and that no property is misspelled
    // into a place the spec does not define it.
    ensureAircraftLayers(map);
    const errors = validateStyleMin(styleForValidation());
    expect(
      errors.map((error) => `${error.identifier}: ${error.message}`),
    ).toEqual([]);
  });

  it("rejects a zoom expression nested inside another expression", () => {
    // The exact mistake `ICON_SIZE` and `ATTENTION_RADIUS` are shaped to
    // avoid, and the reason both fold their per-feature factor into each zoom
    // stop's *output*: `["zoom"]` must be the direct input of a top-level
    // interpolate/step. Multiplying a zoom interpolation by a selection factor
    // looks reasonable and is invalid — this pins that the checks above would
    // catch it rather than waving everything through.
    const spec = propertySpec("symbol", "layout", "icon-size");
    expect(spec).toBeDefined();
    const parsed = createPropertyExpression(
      [
        "*",
        ["interpolate", ["linear"], ["zoom"], 3, 0.6, 11, 1],
        ["case", ["get", "selected"], 1.25, 1],
      ],
      "icon-size",
      spec as StylePropertySpecification,
    );
    expect(parsed.result).toBe("error");
  });

  it("rejects a broken expression in a full-style validation", () => {
    // The negative twin of the whole-style test: proof that
    // `validateStyleMin` is reading these layers rather than shrugging at
    // whatever it is handed.
    ensureAircraftLayers(map);
    const style = styleForValidation();
    const symbols = style.layers.find(
      (layer) => layer.id === AIRCRAFT_SYMBOL_LAYER_ID,
    ) as { layout: Record<string, unknown> } | undefined;
    expect(symbols).toBeDefined();
    // `["get"]` with no argument: a broken expression of exactly the kind
    // that would otherwise be discovered by an empty map at runtime.
    symbols!.layout = { ...symbols!.layout, "icon-rotate": ["get"] };
    expect(validateStyleMin(style).length).toBeGreaterThan(0);
  });
});
