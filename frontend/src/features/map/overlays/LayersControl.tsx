import { ChevronDown, ChevronUp, Layers } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { MapCardPlacement } from "@/features/map/phone/placement";
import { usePhoneMapStore } from "@/features/map/phone/usePhoneMapStore";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { setMapShortcutTarget } from "@/lib/shortcuts/mapShortcutTargets";
import { useAirspaceQuery } from "@/lib/api/overlays";
import { cn } from "@/lib/utils";

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
 *
 * The card collapses to just its header (roadmap slice 082's `L` shortcut):
 * open by default — unlike `FilterDrawer`, which starts closed — since
 * collapsing this card hides no functionality behind an extra click the way
 * the drawer's many fields would; it only reclaims a little map space.
 * Collapse is local, in-memory state, not persisted — a session-scoped
 * convenience, not a preference. Registers `toggleLayersCard` on
 * `lib/shortcuts/mapShortcutTargets` so `useKeyboardShortcuts` (mounted far
 * away, in `AppShell`) can flip it.
 *
 * Docked on a phone (`placement="docked"`, roadmap slice 084) the card sits
 * in the bottom toolbar's Layers sheet, and that sheet is what `L` opens and
 * closes there — so the docked card registers the shortcut against the sheet
 * (`usePhoneMapStore`) instead of its own collapse flag.
 */
export function LayersControl({
  placement = "floating",
}: {
  placement?: MapCardPlacement;
}) {
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

  const [open, setOpen] = useState(true);
  const contentId = useId();

  useEffect(() => {
    setMapShortcutTarget(
      "toggleLayersCard",
      placement === "docked"
        ? () => {
            usePhoneMapStore.getState().toggleCard("layers");
          }
        : () => {
            setOpen((current) => !current);
          },
    );
    return () => {
      setMapShortcutTarget("toggleLayersCard", undefined);
    };
  }, [placement]);

  return (
    <div
      className={cn(
        placement === "floating"
          ? "absolute right-3 top-40 z-10 w-48"
          : "w-full",
        "rounded-lg border border-border bg-card/95 p-2 shadow-md backdrop-blur-sm",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-controls={open ? contentId : undefined}
        className="flex w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium text-muted-foreground outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <Layers className="size-3.5" aria-hidden="true" />
        <span className="flex-1 text-left">Layers</span>
        {open ? (
          <ChevronUp className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        )}
        <span className="sr-only">{open ? "Collapse" : "Expand"}</span>
      </button>
      {open && (
        <div
          id={contentId}
          className="mt-1.5 flex flex-col gap-0.5"
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
              <span className="text-[10px] text-muted-foreground">
                (no data)
              </span>
            )}
          </label>
        </div>
      )}
    </div>
  );
}
