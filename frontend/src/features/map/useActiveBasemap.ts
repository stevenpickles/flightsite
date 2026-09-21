/**
 * The basemap the map should be rendering right now (issue R1-14).
 *
 * Two inputs, one answer: the user's explicit choice if they have made one,
 * otherwise the current theme's affine default. Derived at render rather
 * than synchronised by an effect, which is what keeps a theme toggle from
 * needing to know the map exists — and keeps the two from ever disagreeing
 * about which basemap is current, since there is only one place that is
 * decided.
 *
 * The result is a registry constant, so its identity is stable across
 * renders. `MapLibreMap`'s basemap effect keys on exactly that identity, and
 * a freshly-built object here would call `setStyle` on every render.
 */

import type { BasemapDefinition } from "@/features/map/basemaps";
import { resolveActiveBasemap } from "@/features/map/basemaps";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { useUiStore } from "@/store/useUiStore";

export function useActiveBasemap(): BasemapDefinition {
  const explicitBasemapId = useBasemapStore((state) => state.explicitBasemapId);
  const theme = useUiStore((state) => state.theme);
  return resolveActiveBasemap(explicitBasemapId, theme);
}
