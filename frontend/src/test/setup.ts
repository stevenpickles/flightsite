import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { AttributionControlMock, MapLibreMockMap } from "@/test/maplibreGlMock";

/**
 * MapLibre GL JS requires a real WebGL context, which jsdom does not
 * provide. Every test file that renders map components goes through this
 * same jsdom environment, so the mock is registered once, globally, here
 * rather than repeated per test file — the standard approach for this
 * class of dependency (canvas/WebGL libraries) under jsdom.
 */
vi.mock("maplibre-gl", () => ({
  Map: MapLibreMockMap,
  AttributionControl: AttributionControlMock,
}));

/**
 * Minimal in-memory Storage polyfill.
 *
 * Under this Node/jsdom combination, `window.localStorage` resolves to
 * Node's experimental webstorage global, which throws unless a backing
 * file is configured (`--localstorage-file`). Tests need a real, working
 * Storage so theme-persistence behavior can be exercised faithfully;
 * installing this in-memory implementation sidesteps the environment
 * quirk without changing what the app code under test does.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) ?? null) : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

Object.defineProperty(window, "localStorage", {
  value: new MemoryStorage(),
  writable: true,
  configurable: true,
});

afterEach(() => {
  cleanup();
});
