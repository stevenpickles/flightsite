import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { initMock, resetEchartsMock } from "@/test/echartsMock";
import { AttributionControlMock, MapLibreMockMap } from "@/test/maplibreGlMock";
import { FakeWebSocket, resetWebSocketMock } from "@/test/webSocketMock";

/**
 * ECharts draws to a `<canvas>`, which jsdom does not implement — the same
 * class of problem `maplibre-gl` is mocked for below. See
 * `@/test/echartsMock` for what the mock records and why chart tests assert
 * against the pure option builders instead of a rendered canvas.
 */
vi.mock("echarts", () => ({ init: initMock }));

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
  // MapLibreMap.tsx calls this once at module scope (see its own comment) —
  // a no-op stand-in is enough under jsdom, which never spins up the real
  // worker this configures the URL for.
  setWorkerUrl: vi.fn(),
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

/**
 * jsdom's `WebSocket` is real and would open a network connection as soon as
 * anything renders the Live Map, so the live socket gets the same treatment as
 * MapLibre: one scripted stand-in, installed once, globally. Tests that care
 * about the protocol drive it through `@/test/webSocketMock`.
 */
Object.defineProperty(globalThis, "WebSocket", {
  value: FakeWebSocket,
  writable: true,
  configurable: true,
});

/**
 * jsdom parses `<img>` but never decodes one — no `load` and no `error` fires,
 * so a promise awaiting an image would simply hang. The aircraft icons are SVG
 * data URIs built in-process, with nothing to fetch and nothing that can fail,
 * so a stub that reports a successful decode on the next microtask is a
 * faithful stand-in for the only outcome a browser can produce here.
 */
class StubImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  width = 64;
  height = 64;
  private value = "";

  get src(): string {
    return this.value;
  }

  set src(next: string) {
    this.value = next;
    queueMicrotask(() => {
      this.onload?.();
    });
  }
}

Object.defineProperty(globalThis, "Image", {
  value: StubImage,
  writable: true,
  configurable: true,
});

afterEach(() => {
  cleanup();
  resetWebSocketMock();
  resetEchartsMock();
});
