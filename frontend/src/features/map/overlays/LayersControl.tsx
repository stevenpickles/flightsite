import { Layers } from "lucide-react";

import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { useAirspaceQuery } from "@/lib/api/overlays";

/**
 * Small map-overlay control toggling the Airports and Airspace layers.
 * Visibility is persisted per browser via `useOverlayVisibilityStore`
 * (localStorage, guarded), the same pattern `BasemapSwitcher` uses for the
 * basemap choice. Positioned as a floating card directly beneath it, so the
 * two read as one instrument panel.
 *
 * Airspace defaults on, same as Airports (`DEFAULT_OVERLAY_VISIBILITY`) — an
 * install with no `airspace.geojson` supplied (roadmap slice 028, ADR-0012)
 * simply renders an empty layer, so "on" costs nothing. The "(no data)"
 * suffix here is the only surfaced sign of that state; it is informational,
 * not an error, and it never disables the checkbox.
 */
export function LayersControl() {
  const airports = useOverlayVisibilityStore((state) => state.airports);
  const airspace = useOverlayVisibilityStore((state) => state.airspace);
  const setAirportsVisible = useOverlayVisibilityStore(
    (state) => state.setAirportsVisible,
  );
  const setAirspaceVisible = useOverlayVisibilityStore(
    (state) => state.setAirspaceVisible,
  );
  const airspaceQuery = useAirspaceQuery();
  const airspaceHasData = (airspaceQuery.data?.features.length ?? 0) > 0;

  return (
    <div className="absolute right-3 top-40 z-10 w-48 rounded-lg border border-border bg-card/95 p-2 shadow-md backdrop-blur-sm">
      <div className="mb-1.5 flex items-center gap-1.5 px-1 text-xs font-medium text-muted-foreground">
        <Layers className="size-3.5" aria-hidden="true" />
        <span>Layers</span>
      </div>
      <div
        className="flex flex-col gap-0.5"
        role="group"
        aria-label="Map layers"
      >
        <label className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-foreground hover:bg-secondary">
          <input
            type="checkbox"
            checked={airports}
            onChange={(event) => {
              setAirportsVisible(event.target.checked);
            }}
            className="size-3.5 accent-accent"
          />
          Airports
        </label>
        <label className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-foreground hover:bg-secondary">
          <input
            type="checkbox"
            checked={airspace}
            onChange={(event) => {
              setAirspaceVisible(event.target.checked);
            }}
            className="size-3.5 accent-accent"
          />
          Airspace
          {!airspaceHasData && (
            <span className="text-[10px] text-muted-foreground">(no data)</span>
          )}
        </label>
      </div>
    </div>
  );
}
