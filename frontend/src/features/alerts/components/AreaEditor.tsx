import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { AreaDrawLayer } from "@/features/alerts/components/AreaDrawLayer";
import {
  formatAreaText,
  MAX_AREA_VERTICES,
  readableVertices,
  type Vertex,
} from "@/features/alerts/lib/area";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { useActiveBasemap } from "@/features/map/useActiveBasemap";

export interface AreaEditorProps {
  /** The area as text — one `longitude, latitude` pair per line. */
  text: string;
  onChange: (text: string) => void;
  /** The condition-level error's id, so both inputs are described by it. */
  describedBy?: string;
  invalid: boolean;
}

/**
 * The `within_area` condition's editor (roadmap slice 089): a mini-map to
 * draw on, and a textarea of the same vertices beside it.
 *
 * The map is the ordinary `MapLibreMap` — the receiver marker, range rings,
 * the active basemap and the WebGL-less fallback all come with it — with
 * `AreaDrawLayer` mounted as its overlay. Click to add vertices, drag one to
 * move it, double-click or press Enter to finish; "Clear" starts over and
 * "Undo" drops the last vertex.
 *
 * The textarea is not a debug view, it is the keyboard-accessible way to
 * enter an area (and the only way where WebGL is unavailable): one
 * `longitude, latitude` pair per line, longitude first as GeoJSON has it.
 * Both edit one string, so typing a pair moves the map's vertex and dragging
 * the vertex rewrites the line. While a line is half-typed the map draws the
 * lines that do read as pairs (`readableVertices`) rather than flickering to
 * nothing; a map edit then rewrites the text from those.
 */
export function AreaEditor({
  text,
  onChange,
  describedBy,
  invalid,
}: AreaEditorProps) {
  const textId = useId();
  const helpId = `${textId}-help`;
  const config = useMapConfigStore((state) => state.config);
  const basemap = useActiveBasemap();

  const vertices = readableVertices(text);
  const [drawing, setDrawing] = useState(vertices.length < 3);

  function write(next: readonly Vertex[]): void {
    onChange(formatAreaText(next));
  }

  const canFinish = vertices.length >= 3;

  return (
    <div className="flex flex-col gap-3">
      <div
        className="flex flex-col gap-2"
        onKeyDown={(event) => {
          if (event.key === "Enter" && drawing && canFinish) {
            event.preventDefault();
            setDrawing(false);
          }
        }}
      >
        <MapLibreMap
          config={config}
          basemap={basemap}
          ariaLabel={
            drawing
              ? "Area map: click to add vertices, double-click or press Enter to finish"
              : "Area map: drag a vertex to move it"
          }
          className="h-64 overflow-hidden rounded-md border border-border"
        >
          <AreaDrawLayer
            vertices={vertices}
            drawing={drawing}
            onChange={write}
            onFinish={() => {
              setDrawing(false);
            }}
          />
        </MapLibreMap>

        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {vertices.length} of {MAX_AREA_VERTICES} vertices
            {drawing
              ? " · Click the map to add a vertex; double-click or press Enter to finish."
              : " · Drag a vertex to move it."}
          </p>
          <div className="ml-auto flex gap-2">
            {drawing ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!canFinish}
                onClick={() => {
                  setDrawing(false);
                }}
              >
                Finish shape
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={vertices.length >= MAX_AREA_VERTICES}
                onClick={() => {
                  setDrawing(true);
                }}
              >
                Add vertices
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={vertices.length === 0}
              onClick={() => {
                write(vertices.slice(0, -1));
              }}
            >
              Undo vertex
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={text.length === 0}
              onClick={() => {
                onChange("");
                setDrawing(true);
              }}
            >
              Clear
            </Button>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={textId}>Vertices (longitude, latitude)</Label>
        <textarea
          id={textId}
          className="min-h-24 w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          value={text}
          rows={5}
          spellCheck={false}
          placeholder={"-1.5, 50.9\n-1.2, 50.9\n-1.2, 51.1"}
          aria-invalid={invalid}
          aria-describedby={[helpId, describedBy].filter(Boolean).join(" ")}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
        <p id={helpId} className="text-xs text-muted-foreground">
          One vertex per line, longitude first, in decimal degrees — the same
          shape the map draws. 3 to {MAX_AREA_VERTICES} vertices; the shape is
          closed for you. An area cannot cross the 180° meridian or have holes,
          and its edges cannot cross.
        </p>
      </div>
    </div>
  );
}
