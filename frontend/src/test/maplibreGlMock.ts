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
  removed = false;
  // Mirrors real MapLibre: false immediately after construction (or after
  // setStyle swaps the style) until a `load`/`style.load` event fires.
  styleLoaded = false;

  addControl = vi.fn();
  setStyle = vi.fn(() => {
    this.styleLoaded = false;
  });
  jumpTo = vi.fn();

  constructor(options: Record<string, unknown>) {
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

  once(event: string, handler: MockEventHandler): this {
    const wrapped: MockEventHandler = (payload) => {
      handler(payload);
      this.off(event, wrapped);
    };
    return this.on(event, wrapped);
  }

  off(event: string, handler: MockEventHandler): this {
    this.handlers.get(event)?.delete(handler);
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
