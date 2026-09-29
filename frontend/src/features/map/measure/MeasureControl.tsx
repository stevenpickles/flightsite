/**
 * The Live Map's distance/bearing measure tool (roadmap slice 085, issue
 * #228) — the visible control, the map wiring, and the one subscriber to
 * `useMeasureStore`.
 *
 * **Flow.** The ruler button (or `M`) turns measure mode on. The first map
 * click places point A, the second places B and draws the great-circle line
 * between them with its distance — in the receiver's units — and initial
 * bearing, both on the map at the line's midpoint and in the readout beside
 * the button. A third click starts over from a new A. "From receiver" makes
 * the receiver A, so the next click measures range and bearing from the
 * antenna. The button again, or Escape, leaves measure mode and clears the
 * line.
 *
 * **Clicks belong to the tool while it is on.** `useAircraftLayer`'s
 * selection handler checks `useMeasureStore` and stands down, so a click
 * that lands on an aircraft places a point instead of selecting it — and a
 * click on empty map does not clear an existing selection either. The
 * cursor turns to a crosshair for as long as that is true.
 *
 * **Escape** is taken in the capture phase on `window` and stopped there,
 * but only while measuring: Escape has one meaning at a time, and while the
 * tool is on that meaning is "stop measuring", not also "deselect the
 * aircraft" (`AircraftDetailPanel`) or "close the filter drawer".
 *
 * Rendered as a child of `MapLibreMap`, like `RecenterButton` — which it
 * sits beside, in the top-left group the phone layout also keeps on the map
 * (`phone/PhoneMapControls`), so it needs no second placement. Leaving the
 * Live Map leaves measure mode.
 */

import { Ruler } from "lucide-react";
import type { MapMouseEvent } from "maplibre-gl";
import { useEffect, useId } from "react";

import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useMapInstance } from "@/features/map/MapInstanceContext";
import {
  buildMeasureFeatureCollection,
  ensureMeasureLayers,
  setMeasureData,
} from "@/features/map/measure/measureLayers";
import {
  describeMeasurement,
  measure,
} from "@/features/map/measure/measureMath";
import { useMeasureStore } from "@/features/map/measure/useMeasureStore";
import type { ReceiverPosition } from "@/features/map/types";
import { cn } from "@/lib/utils";

const PILL_CLASSES =
  "pointer-events-auto rounded-full border border-border bg-card/95 text-xs shadow-sm backdrop-blur-sm";

const FOCUS_CLASSES =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

export function MeasureControl({
  receiver,
}: {
  /** The receiver to measure from, or `null` when no real location is
   * configured — then there is no "From receiver" option (issue R1-05: a
   * placeholder position is not a place to measure from). */
  receiver: ReceiverPosition | null;
}) {
  const { map, styleEpoch } = useMapInstance();
  const active = useMeasureStore((state) => state.active);
  const points = useMeasureStore((state) => state.points);
  const toggle = useMeasureStore((state) => state.toggle);
  const startFrom = useMeasureStore((state) => state.startFrom);
  const units =
    useLiveAircraftStore((state) => state.receiver?.units) ?? "aviation";
  const readoutId = useId();

  // Attach after each style load; a basemap switch discards custom layers.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    ensureMeasureLayers(map);
  }, [map, styleEpoch]);

  // Feed: the current points, redrawn on every change and every re-attach.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    setMeasureData(map, buildMeasureFeatureCollection(points, units));
  }, [map, styleEpoch, points, units]);

  // Clicks place points. Registered for the life of the map rather than per
  // mode, and reading the mode at click time, so a click can never race a
  // re-registration.
  useEffect(() => {
    if (!map) {
      return undefined;
    }
    const handleClick = (event: MapMouseEvent) => {
      const store = useMeasureStore.getState();
      if (!store.active) {
        return;
      }
      store.addPoint({ lat: event.lngLat.lat, lon: event.lngLat.lng });
    };
    map.on("click", handleClick);
    return () => {
      map.off("click", handleClick);
    };
  }, [map]);

  // Crosshair cursor while measuring.
  useEffect(() => {
    if (!map || !active) {
      return undefined;
    }
    const canvas = map.getCanvas();
    const previous = canvas.style.cursor;
    canvas.style.cursor = "crosshair";
    return () => {
      canvas.style.cursor = previous;
    };
  }, [map, active]);

  // Escape leaves measure mode — and only that; see the module docstring.
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        useMeasureStore.getState().exit();
      }
    }
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [active]);

  // Leaving the Live Map leaves measure mode.
  useEffect(
    () => () => {
      useMeasureStore.getState().exit();
    },
    [],
  );

  const [from, to] = points;
  const readout = !active
    ? null
    : from && to
      ? describeMeasurement(measure(from, to), units)
      : from
        ? "Click the map to set point B"
        : "Click the map to set point A";

  return (
    <div className="pointer-events-none absolute left-12 top-20 z-10 flex max-w-[calc(100%-4rem)] flex-wrap items-center gap-1.5">
      <button
        type="button"
        onClick={toggle}
        aria-pressed={active}
        aria-label="Measure distance and bearing"
        aria-describedby={readoutId}
        title="Measure distance and bearing (M)"
        className={cn(
          PILL_CLASSES,
          FOCUS_CLASSES,
          "p-1.5 transition-colors",
          active
            ? "border-accent bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-secondary hover:text-foreground",
        )}
      >
        <Ruler className="size-3.5" aria-hidden="true" />
      </button>
      {active && receiver !== null && (
        <button
          type="button"
          onClick={() => {
            startFrom({ lat: receiver.lat, lon: receiver.lon });
          }}
          className={cn(
            PILL_CLASSES,
            FOCUS_CLASSES,
            "px-2 py-1 text-foreground transition-colors hover:bg-secondary",
          )}
        >
          From receiver
        </button>
      )}
      {/* Always mounted, so screen readers have the live region before the
       * first readout lands in it; empty and visually hidden while off. */}
      <p
        id={readoutId}
        role="status"
        data-testid="measure-readout"
        className={
          readout === null
            ? "sr-only"
            : cn(PILL_CLASSES, "px-2 py-1 font-medium tabular-nums")
        }
      >
        {readout}
      </p>
    </div>
  );
}
