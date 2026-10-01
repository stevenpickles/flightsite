/**
 * Draws, and lets the user edit, a rule's area on the enclosing `MapLibreMap`
 * (roadmap slice 089).
 *
 * The same composition `SightingPathLayer` uses: client-drawn GeoJSON
 * attached imperatively to the instance `MapInstanceContext` provides, and
 * re-attached on every `styleEpoch` so a basemap switch cannot erase it.
 * The layer is controlled — it draws the vertices it is given and *reports*
 * edits through callbacks; the area editor owns the state (as text, see
 * `lib/area.ts`), which is what keeps the map and the keyboard fallback in
 * step.
 *
 * Interactions:
 *
 * - **Click** adds a vertex while drawing. The two clicks of a double-click
 *   land on the same rounded coordinate, and a vertex identical to the last
 *   one is ignored, so a double-click places one final vertex.
 * - **Double-click** finishes drawing. Double-click zoom is switched off
 *   while drawing so the gesture means one thing.
 * - **Drag** a vertex to move it, drawing or not. Map panning is switched off
 *   for the length of the drag, and the click that ends a drag is swallowed
 *   so moving a vertex never also adds one.
 *
 * Vertices are found under the pointer with `queryRenderedFeatures` on the
 * vertex layer, so hit-testing uses the rendered circle radius rather than a
 * second geometry calculation here.
 */

import { useEffect, useRef } from "react";

import type {
  GeoJSONSource,
  Map as MapLibreGlMap,
  MapMouseEvent,
} from "maplibre-gl";

import {
  buildAreaGeojson,
  MAX_AREA_VERTICES,
  roundCoordinate,
  type Vertex,
} from "@/features/alerts/lib/area";
import { useMapInstance } from "@/features/map/MapInstanceContext";

export const AREA_SOURCE_ID = "flightsite-alert-area";
export const AREA_VERTICES_SOURCE_ID = "flightsite-alert-area-vertices";
export const AREA_FILL_LAYER_ID = "flightsite-alert-area-fill";
export const AREA_LINE_LAYER_ID = "flightsite-alert-area-line";
export const AREA_VERTEX_LAYER_ID = "flightsite-alert-area-vertex";

/** The accent the sighting path and measure tool already use, so a drawn
 * shape reads as "something you made" rather than as map data. */
const AREA_COLOR = "#4dd8cf";

function upsertSource(
  map: MapLibreGlMap,
  id: string,
  data: GeoJSON.FeatureCollection,
): void {
  const existing = map.getSource(id) as GeoJSONSource | undefined;
  if (existing) {
    existing.setData(data);
  } else {
    map.addSource(id, { type: "geojson", data });
  }
}

function ensureLayers(map: MapLibreGlMap): void {
  if (!map.getLayer(AREA_FILL_LAYER_ID)) {
    map.addLayer({
      id: AREA_FILL_LAYER_ID,
      type: "fill",
      source: AREA_SOURCE_ID,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": AREA_COLOR, "fill-opacity": 0.15 },
    });
  }
  if (!map.getLayer(AREA_LINE_LAYER_ID)) {
    map.addLayer({
      id: AREA_LINE_LAYER_ID,
      type: "line",
      source: AREA_SOURCE_ID,
      paint: { "line-color": AREA_COLOR, "line-width": 2 },
    });
  }
  if (!map.getLayer(AREA_VERTEX_LAYER_ID)) {
    map.addLayer({
      id: AREA_VERTEX_LAYER_ID,
      type: "circle",
      source: AREA_VERTICES_SOURCE_ID,
      paint: {
        "circle-radius": 6,
        "circle-color": "#ffffff",
        "circle-stroke-color": AREA_COLOR,
        "circle-stroke-width": 2,
      },
    });
  }
}

function vertexOf(event: MapMouseEvent): Vertex {
  return [roundCoordinate(event.lngLat.lng), roundCoordinate(event.lngLat.lat)];
}

export interface AreaDrawLayerProps {
  vertices: readonly Vertex[];
  /** True while clicks add vertices. */
  drawing: boolean;
  /** The whole new vertex list after an add or a move. */
  onChange: (next: Vertex[]) => void;
  onFinish: () => void;
}

export function AreaDrawLayer({
  vertices,
  drawing,
  onChange,
  onFinish,
}: AreaDrawLayerProps) {
  const { map, styleEpoch } = useMapInstance();
  // Handlers are registered once per map and read the latest props through
  // this ref — the same reason `MapLibreMap` keeps `onMapClick` in a ref: a
  // new callback identity every render must not re-register map listeners.
  // The handlers also write their own result back into it, so two events
  // arriving before React re-renders (the two clicks of a double-click)
  // each see the vertex list the previous one produced.
  const latest = useRef({ vertices, drawing, onChange, onFinish });
  useEffect(() => {
    latest.current = { vertices, drawing, onChange, onFinish };
  });
  const fittedRef = useRef(false);

  // Draw (and re-draw after a style swap).
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    const geojson = buildAreaGeojson(vertices);
    upsertSource(map, AREA_SOURCE_ID, geojson.shape);
    upsertSource(map, AREA_VERTICES_SOURCE_ID, geojson.points);
    ensureLayers(map);
    // Fit an existing area into view once, when the editor opens on a saved
    // rule — never again, or every vertex drag would fight the camera.
    if (!fittedRef.current && vertices.length >= 3) {
      fittedRef.current = true;
      const lons = vertices.map((vertex) => vertex[0]);
      const lats = vertices.map((vertex) => vertex[1]);
      map.fitBounds(
        [
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        ],
        { padding: 32, maxZoom: 12, duration: 0 },
      );
    }
  }, [map, styleEpoch, vertices]);

  // Double-click means "finish" only while drawing.
  useEffect(() => {
    if (!map) {
      return;
    }
    if (drawing) {
      map.doubleClickZoom.disable();
    } else {
      map.doubleClickZoom.enable();
    }
  }, [map, drawing]);

  useEffect(() => {
    if (!map) {
      return undefined;
    }
    let dragIndex: number | null = null;
    let dragged = false;

    const handleMouseDown = (event: MapMouseEvent) => {
      const hits = map.queryRenderedFeatures(event.point, {
        layers: [AREA_VERTEX_LAYER_ID],
      });
      const index = hits[0]?.properties.index as unknown;
      if (typeof index !== "number") {
        return;
      }
      event.preventDefault();
      dragIndex = index;
      dragged = false;
      map.dragPan.disable();
    };
    const report = (next: Vertex[]) => {
      latest.current.vertices = next;
      latest.current.onChange(next);
    };
    const handleMouseMove = (event: MapMouseEvent) => {
      if (dragIndex === null) {
        return;
      }
      dragged = true;
      const moved = vertexOf(event);
      const index = dragIndex;
      report(
        latest.current.vertices.map((existing, position) =>
          position === index ? moved : existing,
        ),
      );
    };
    const handleMouseUp = () => {
      if (dragIndex === null) {
        return;
      }
      dragIndex = null;
      map.dragPan.enable();
    };
    const handleClick = (event: MapMouseEvent) => {
      if (dragged) {
        dragged = false;
        return;
      }
      const { drawing: isDrawing, vertices: current } = latest.current;
      if (!isDrawing || current.length >= MAX_AREA_VERTICES) {
        return;
      }
      const vertex = vertexOf(event);
      const last = current.at(-1);
      if (last && last[0] === vertex[0] && last[1] === vertex[1]) {
        return;
      }
      report([...current, vertex]);
    };
    const handleDoubleClick = (event: MapMouseEvent) => {
      if (!latest.current.drawing) {
        return;
      }
      event.preventDefault();
      latest.current.drawing = false;
      latest.current.onFinish();
    };

    map.on("mousedown", handleMouseDown);
    map.on("mousemove", handleMouseMove);
    map.on("mouseup", handleMouseUp);
    map.on("click", handleClick);
    map.on("dblclick", handleDoubleClick);
    return () => {
      map.off("mousedown", handleMouseDown);
      map.off("mousemove", handleMouseMove);
      map.off("mouseup", handleMouseUp);
      map.off("click", handleClick);
      map.off("dblclick", handleDoubleClick);
    };
  }, [map]);

  return null;
}
