import { vi } from "vitest";

/**
 * jsdom has no canvas/2D rendering context, so a real `echarts.init` either
 * throws or silently draws nothing — the same class of problem
 * `maplibreGlMock.ts` solves for MapLibre. Rather than assert against
 * ECharts' internal call sequence, this mock is a thin recorder: every
 * `EChart` component test asserts against the pure `chartOptions.ts`
 * builders directly (no DOM needed) and against the wrapper's own plumbing
 * (init/setOption/resize/dispose called at the right times) — never against
 * what a real canvas drew.
 */
export interface MockChartInstance {
  setOption: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  dispose: ReturnType<typeof vi.fn>;
  /** The most recent `option` argument `setOption` was called with. */
  lastOption: unknown;
}

export const mockChartInstances: MockChartInstance[] = [];

export function resetEchartsMock(): void {
  mockChartInstances.length = 0;
}

export const initMock = vi.fn((_container: HTMLElement): MockChartInstance => {
  const instance: MockChartInstance = {
    lastOption: undefined,
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  };
  instance.setOption.mockImplementation((option: unknown) => {
    instance.lastOption = option;
  });
  mockChartInstances.push(instance);
  return instance;
});
