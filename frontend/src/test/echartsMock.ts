import { vi } from "vitest";

/**
 * A minimal stand-in for `echarts/core`'s `init`/`use`, used globally via
 * `vi.mock("echarts/core", ...)` in `test/setup.ts`. ECharts' `CanvasRenderer`
 * needs a real 2D canvas context, which jsdom does not provide — mocking the
 * module (rather than the canvas) is the same approach this suite already
 * takes for `maplibre-gl`'s WebGL requirement (`test/maplibreGlMock.ts`), and
 * keeps every test that merely navigates through the Analytics route (e.g.
 * the full-route sweep in `routes.test.tsx`) from touching real chart
 * rendering at all.
 *
 * `EChart.tsx` (roadmap slice 032) is the only production code that calls
 * `init`; its own tests use `getLastMockChart`/`resetEchartsMock` to assert
 * `setOption`/`resize`/`dispose` calls and to drive `on("click", ...)`
 * handlers directly.
 */

export type MockEventHandler = (params?: unknown) => void;

export class MockEChartsInstance {
  static instances: MockEChartsInstance[] = [];

  readonly dom: Element;
  /** Every `setOption` call's argument, in order — lets a test assert the
   * final (or a specific) themed option without re-deriving it. */
  readonly optionCalls: unknown[] = [];
  disposed = false;
  private readonly handlers = new Map<string, Set<MockEventHandler>>();

  constructor(dom: Element) {
    this.dom = dom;
    MockEChartsInstance.instances.push(this);
  }

  setOption = vi.fn((option: unknown) => {
    this.optionCalls.push(option);
  });

  resize = vi.fn();

  on = vi.fn((event: string, handler: MockEventHandler) => {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)?.add(handler);
  });

  off = vi.fn((event: string, handler: MockEventHandler) => {
    this.handlers.get(event)?.delete(handler);
  });

  dispose = vi.fn(() => {
    this.disposed = true;
  });

  /** Test-only helper: invokes every handler registered for `event` (e.g.
   * `"click"`) — simulates a user interacting with the (unrendered) chart. */
  emit(event: string, params?: unknown): void {
    for (const handler of this.handlers.get(event) ?? []) {
      handler(params);
    }
  }
}

export const init = vi.fn(
  (dom: Element): MockEChartsInstance => new MockEChartsInstance(dom),
);
export const use = vi.fn();

/** Resets captured instances and call history between tests. */
export function resetEchartsMock(): void {
  MockEChartsInstance.instances = [];
  init.mockClear();
  use.mockClear();
}

/** Returns the most recently constructed mock chart instance. Throws if none
 * exists yet — a test bug (asserting before the chart mounted), not a case
 * to guard defensively against. */
export function getLastMockChart(): MockEChartsInstance {
  const instance = MockEChartsInstance.instances.at(-1);
  if (!instance) {
    throw new Error("No MockEChartsInstance instance has been constructed yet");
  }
  return instance;
}
