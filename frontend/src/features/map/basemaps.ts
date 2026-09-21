import type { StyleSpecification } from "maplibre-gl";

import { darkAviationStyle } from "@/features/map/basemaps/darkAviationStyle";
import { lightAviationStyle } from "@/features/map/basemaps/lightAviationStyle";
import {
  OSM_ATTRIBUTION,
  osmRasterStyle,
} from "@/features/map/basemaps/osmRasterStyle";
import { OPENFREEMAP_ATTRIBUTION } from "@/features/map/basemaps/paletteStyleFactory";

/** Which app theme a basemap is designed to sit alongside. Used by UI that
 * wants to suggest a sensible default per theme; it never hides options. */
export type BasemapThemeAffinity = "dark" | "light";

export interface BasemapDefinition {
  id: string;
  label: string;
  description: string;
  /** A full MapLibre style object, or a URL MapLibre should fetch one
   * from. All registry entries currently ship inline objects so the exact
   * tiles/attribution/licensing in use are reviewable in this repo rather
   * than at a third party's discretion; the type stays a union so a
   * future entry can point at a hosted style JSON if that's ever the
   * better tradeoff. */
  style: StyleSpecification | string;
  /** HTML attribution string, always rendered regardless of whether the
   * style's own sources also declare one. */
  attribution: string;
  themeAffinity: BasemapThemeAffinity;
  /** Whether selecting this basemap requires the user to supply their own
   * API key. Every entry in this registry is false — see
   * docs/adr/0011-default-basemap-provider.md for why a keyless default
   * was required, not just preferred. */
  requiresKey: boolean;
}

/**
 * The basemap registry: every basemap the Live Map can render, keyed by a
 * stable id. `dark-aviation` is the default (docs/adr/0011). All entries
 * are free, keyless, and licensed for this use — see docs/LICENSES.md.
 */
export const BASEMAPS: readonly BasemapDefinition[] = [
  {
    id: "dark-aviation",
    label: "Dark Aviation",
    description:
      "Near-black, blue-tinted default styled for night ops and radar-style reading.",
    style: darkAviationStyle,
    attribution: OPENFREEMAP_ATTRIBUTION,
    themeAffinity: "dark",
    requiresKey: false,
  },
  {
    id: "light-aviation",
    label: "Light Aviation",
    description:
      "The same map content in a bright palette for daylight/high-glare use.",
    style: lightAviationStyle,
    attribution: OPENFREEMAP_ATTRIBUTION,
    themeAffinity: "light",
    requiresKey: false,
  },
  {
    id: "osm-raster",
    label: "OpenStreetMap",
    description:
      "Standard OpenStreetMap raster tiles — a universal fallback with no vendor dependency.",
    style: osmRasterStyle,
    attribution: OSM_ATTRIBUTION,
    themeAffinity: "light",
    requiresKey: false,
  },
] as const;

export const DEFAULT_BASEMAP_ID: string = "dark-aviation";

export function isValidBasemapId(id: string): boolean {
  return BASEMAPS.some((basemap) => basemap.id === id);
}

export function getBasemapById(id: string): BasemapDefinition | undefined {
  return BASEMAPS.find((basemap) => basemap.id === id);
}

/** The default basemap definition. Throws only if the registry itself is
 * misconfigured (missing its own default entry) — a programming error. */
export function getDefaultBasemap(): BasemapDefinition {
  const basemap = getBasemapById(DEFAULT_BASEMAP_ID);
  if (!basemap) {
    throw new Error(
      `Default basemap "${DEFAULT_BASEMAP_ID}" is missing from the registry`,
    );
  }
  return basemap;
}

/**
 * The basemap to show under `theme` when the user has not chosen one.
 *
 * This is what {@link BasemapDefinition.themeAffinity} was declared for, and
 * until issue R1-14 nothing read it: a light-theme user got bright panels
 * floating over the near-black `dark-aviation` default (sampled at
 * `(10,14,26)` in both themes while the chrome switched correctly), and the
 * only way out was finding the basemap switcher. First registry entry whose
 * affinity matches, so the order in {@link BASEMAPS} is the preference
 * order; the registry default if a theme somehow has no match at all.
 */
export function getThemeDefaultBasemap(
  theme: BasemapThemeAffinity,
): BasemapDefinition {
  return (
    BASEMAPS.find((basemap) => basemap.themeAffinity === theme) ??
    getDefaultBasemap()
  );
}

/**
 * The basemap actually in force: the user's explicit choice if they have
 * made one, otherwise the theme's default.
 *
 * An explicit choice is sticky across theme changes on purpose — someone
 * who picked OpenStreetMap wants OpenStreetMap, in either theme — so the
 * theme only ever decides what has not been decided. `explicitId` is `null`
 * when nothing has been chosen and is also treated as nothing when it names
 * a basemap this build does not have.
 */
export function resolveActiveBasemap(
  explicitId: string | null,
  theme: BasemapThemeAffinity,
): BasemapDefinition {
  const explicit = explicitId === null ? undefined : getBasemapById(explicitId);
  return explicit ?? getThemeDefaultBasemap(theme);
}
