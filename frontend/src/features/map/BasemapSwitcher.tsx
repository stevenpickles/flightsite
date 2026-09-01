import { Layers } from "lucide-react";
import { useRef } from "react";

import { BASEMAPS } from "@/features/map/basemaps";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { useRovingFocus } from "@/lib/a11y/useRovingFocus";
import { cn } from "@/lib/utils";

/**
 * Small map-overlay control listing every registered basemap. Selection is
 * persisted per browser via `useBasemapStore` (localStorage, guarded).
 * Positioned as a floating card so it reads as part of the map instrument
 * panel rather than a page-level settings control.
 */
export function BasemapSwitcher() {
  const basemapId = useBasemapStore((state) => state.basemapId);
  const setBasemapId = useBasemapStore((state) => state.setBasemapId);
  // Vertically stacked options, so Up/Down are the natural arrows.
  const groupRef = useRef<HTMLDivElement>(null);
  const onKeyDown = useRovingFocus(groupRef, {
    itemRole: "radio",
    orientation: "vertical",
  });

  return (
    <div className="absolute right-3 top-3 z-10 w-48 rounded-lg border border-border bg-card/95 p-2 shadow-md backdrop-blur-sm">
      <div className="mb-1.5 flex items-center gap-1.5 px-1 text-xs font-medium text-muted-foreground">
        <Layers className="size-3.5" aria-hidden="true" />
        <span>Basemap</span>
      </div>
      <div
        role="radiogroup"
        aria-label="Basemap"
        ref={groupRef}
        onKeyDown={onKeyDown}
        className="flex flex-col gap-0.5"
      >
        {BASEMAPS.map((basemap) => {
          const selected = basemap.id === basemapId;
          return (
            <button
              key={basemap.id}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              title={basemap.description}
              onClick={() => {
                setBasemapId(basemap.id);
              }}
              className={cn(
                "rounded-md px-2 py-1.5 text-left text-xs outline-none transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                selected
                  ? "bg-accent text-accent-foreground"
                  : "text-foreground hover:bg-secondary",
              )}
            >
              {basemap.label}
              {basemap.requiresKey && (
                <span className="ml-1 text-[10px] text-muted-foreground">
                  (key required)
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
