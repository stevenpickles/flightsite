import { vi } from "vitest";

/**
 * A minimal stand-in for the `maplibre-gl` module's `Map`/`AttributionControl`
 * classes, used by component tests via `vi.mock("maplibre-gl", ...)`.
 * MapLibre GL JS requires a real WebGL context, which jsdom does not
 * provide — mocking it is the standard approach (see slice 013 test plan).
 *
 * Captures event handlers so tests can drive them directly (`emit`) to
 * simulate `load`, `error`, and `style.load` without a real renderer.
 */

export type MockEventHandler = (event?: unknown) => void;

interface MockSource {
  setData: ReturnType<typeof vi.fn>;
  /** Most recent data the source was given — whatever `addSource` was called
   * with, then whatever the last `setData` passed. Lets tests assert on the
   * GeoJSON a layer actually pushed. */
  data: unknown;
}

/** Minimal stand-in for a queried rendered feature. */
export interface MockRenderedFeature {
  properties: Record<string, unknown>;
}

export class MapLibreMockMap {
  static instances: MapLibreMockMap[] = [];

  options: Record<string, unknown>;
  handlers = new Map<string, Set<MockEventHandler>>();
  /** `once` registrations, keyed by the caller's own handler — see `once`. */
  onceWrappers = new Map<MockEventHandler, MockEventHandler>();
  sources = new Map<string, MockSource>();
  layers = new Map<string, Record<string, unknown>>();
  images = new Map<string, unknown>();
  /** Features `queryRenderedFeatures` returns; tests set this to simulate a
   * click landing on an aircraft. */
  renderedFeatures: MockRenderedFeature[] = [];
  /** `getZoom()`'s return value. Defaults into the "full label stack" band
   * (`ZOOM_LABELS_FULL` in `features/map/labels/priority.ts`) so a test that
   * does not care about zoom-driven decluttering sees the full picture;
   * tests that do care set this directly. */
  zoom = 10;
  /** `getBounds()`'s return value — `west`/`south`/`east`/`north` in decimal
   * degrees. Defaults to a small box around the Seattle area (arbitrary but
   * plausible) so the airport overlay's viewport-driven fetch
   * (`features/map/overlays/useMapViewport.ts`) has something to read
   * without every test needing to set it; tests that care set this
   * directly. */
  bounds = { west: -123.0, south: 47.0, east: -121.9, north: 47.8 };
  removed = false;
  // Mirrors real MapLibre: false immediately after construction (or after
  // setStyle swaps the style) until a `load`/`style.load` event fires.
  styleLoaded = false;

  addControl = vi.fn();
  /**
   * Mirrors what `Map.setStyle` actually does to an inline style object,
   * which is what every registry entry is (issue R1-01).
   *
   * `setStyle` defaults to `diff: true`, so for an object style it runs
   * `Style.setState` **synchronously**: every layer, source and image the
   * next style does not declare — all of FlightSite's, since they are added
   * imperatively — is removed, and `style.load` is fired before the call
   * returns (maplibre-gl 6.6.0). This mock previously did neither: it
   * emitted nothing and left the layers in place, so the basemap-switch test
   * passed against code that registered its `style.load` handler *after*
   * `setStyle` and could therefore never re-add anything. Firing the event
   * here is what makes that test exercise the ordering rather than assume it.
   */
  setStyle = vi.fn(() => {
    this.layers.clear();
    this.sources.clear();
    this.images.clear();
    this.styleLoaded = false;
    this.emit("style.load");
  });
  jumpTo = vi.fn();
  fitBounds = vi.fn();

  /** When true, the next construction throws — simulating a browser with
   * no WebGL context (MapLibre throws from its constructor there). Reset by
   * `resetMapLibreMock`. */
  static throwOnNextConstruct = false;

  constructor(options: Record<string, unknown>) {
    if (MapLibreMockMap.throwOnNextConstruct) {
      MapLibreMockMap.throwOnNextConstruct = false;
      throw new Error("Failed to initialize WebGL");
    }
    this.options = options;
    MapLibreMockMap.instances.push(this);
  }

  on(event: string, handler: MockEventHandler): this {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)?.add(handler);
    return this;
  }

  /** Registered under the *caller's* handler, not the self-removing wrapper,
   * so `off(event, handler)` unregisters it — real MapLibre's `Evented.off`
   * searches `_oneTimeListeners` by the original listener too, and a cleanup
   * that silently failed to detach would leave a stale handler firing on the
   * next style swap. */
  once(event: string, handler: MockEventHandler): this {
    const wrapped: MockEventHandler = (payload) => {
      this.off(event, handler);
      handler(payload);
    };
    this.onceWrappers.set(handler, wrapped);
    return this.on(event, wrapped);
  }

  off(event: string, handler: MockEventHandler): this {
    const listeners = this.handlers.get(event);
    listeners?.delete(handler);
    const wrapped = this.onceWrappers.get(handler);
    if (wrapped) {
      listeners?.delete(wrapped);
      this.onceWrappers.delete(handler);
    }
    return this;
  }

  /** Test-only helper: invokes every handler registered for `event`. */
  emit(event: string, payload?: unknown): void {
    if (event === "load" || event === "style.load") {
      this.styleLoaded = true;
    }
    for (const handler of this.handlers.get(event) ?? []) {
      handler(payload);
    }
  }

  addSource(id: string, source?: { data?: unknown }): void {
    const entry: MockSource = {
      data: source?.data,
      setData: vi.fn((data: unknown) => {
        entry.data = data;
      }),
    };
    this.sources.set(id, entry);
  }

  getSource(id: string): MockSource | undefined {
    return this.sources.get(id);
  }

  addLayer(layer: { id: string } & Record<string, unknown>): this {
    this.layers.set(layer.id, layer);
    return this;
  }

  getLayer(id: string): Record<string, unknown> | undefined {
    return this.layers.get(id);
  }

  /** Updates a layer's `layout` object in place, mirroring real MapLibre's
   * `setLayoutProperty` — used by the overlay toggles
   * (`setAirportLayersVisible`/`setAirspaceLayersVisible`) to flip
   * `visibility` without a refetch. No-ops for an unknown layer id, the
   * same as the real map. */
  setLayoutProperty(layerId: string, prop: string, value: unknown): void {
    const layer = this.layers.get(layerId);
    if (!layer) {
      return;
    }
    const layout = { ...((layer.layout as Record<string, unknown>) ?? {}) };
    layout[prop] = value;
    layer.layout = layout;
  }

  getBounds(): {
    getWest: () => number;
    getSouth: () => number;
    getEast: () => number;
    getNorth: () => number;
  } {
    const { west, south, east, north } = this.bounds;
    return {
      getWest: () => west,
      getSouth: () => south,
      getEast: () => east,
      getNorth: () => north,
    };
  }

  hasImage(id: string): boolean {
    return this.images.has(id);
  }

  addImage(id: string, image: unknown): void {
    this.images.set(id, image);
  }

  queryRenderedFeatures(): MockRenderedFeature[] {
    return this.renderedFeatures;
  }

  getZoom(): number {
    return this.zoom;
  }

  isStyleLoaded(): boolean {
    return this.styleLoaded;
  }

  remove(): void {
    this.removed = true;
  }
}

export class AttributionControlMock {
  options: unknown;
  constructor(options?: unknown) {
    this.options = options;
  }
}

/** Resets captured instances between tests. */
export function resetMapLibreMock(): void {
  MapLibreMockMap.instances = [];
  MapLibreMockMap.throwOnNextConstruct = false;
}

/** Returns the most recently constructed mock map instance. Throws if none
 * exists yet — a test bug (render before asserting), not a case to guard
 * defensively against. */
export function getLastMockMap(): MapLibreMockMap {
  const map = MapLibreMockMap.instances.at(-1);
  if (!map) {
    throw new Error("No MapLibreMockMap instance has been constructed yet");
  }
  return map;
}
