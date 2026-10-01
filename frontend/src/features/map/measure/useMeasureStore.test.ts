import { afterEach, describe, expect, it } from "vitest";

import { useMeasureStore } from "@/features/map/measure/useMeasureStore";

const A = { lat: 47, lon: -122 };
const B = { lat: 48, lon: -121 };
const C = { lat: 46, lon: -123 };

afterEach(() => {
  useMeasureStore.getState().exit();
});

describe("useMeasureStore", () => {
  it("starts off, with nothing placed", () => {
    expect(useMeasureStore.getState()).toMatchObject({
      active: false,
      points: [],
    });
  });

  it("places A, then B, then starts over from a new A", () => {
    const store = useMeasureStore.getState();
    store.toggle();
    store.addPoint(A);
    expect(useMeasureStore.getState().points).toEqual([A]);
    store.addPoint(B);
    expect(useMeasureStore.getState().points).toEqual([A, B]);
    store.addPoint(C);
    expect(useMeasureStore.getState().points).toEqual([C]);
  });

  it("ignores points while off", () => {
    useMeasureStore.getState().addPoint(A);
    expect(useMeasureStore.getState().points).toEqual([]);
    expect(useMeasureStore.getState().active).toBe(false);
  });

  it("toggling off forgets the points, and toggling on starts clean", () => {
    const store = useMeasureStore.getState();
    store.toggle();
    store.addPoint(A);
    store.toggle();
    expect(useMeasureStore.getState()).toMatchObject({
      active: false,
      points: [],
    });
    store.toggle();
    expect(useMeasureStore.getState()).toMatchObject({
      active: true,
      points: [],
    });
  });

  it("exit leaves measure mode and clears the line", () => {
    const store = useMeasureStore.getState();
    store.toggle();
    store.addPoint(A);
    store.addPoint(B);
    store.exit();
    expect(useMeasureStore.getState()).toMatchObject({
      active: false,
      points: [],
    });
  });

  it("startFrom makes the given point A, turning the tool on", () => {
    useMeasureStore.getState().startFrom(A);
    expect(useMeasureStore.getState()).toMatchObject({
      active: true,
      points: [A],
    });
    useMeasureStore.getState().addPoint(B);
    expect(useMeasureStore.getState().points).toEqual([A, B]);
  });
});
