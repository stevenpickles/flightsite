import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_OVERLAY_VISIBILITY,
  OVERLAY_VISIBILITY_STORAGE_KEY,
} from "@/features/map/overlayVisibilityPersistence";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";

afterEach(() => {
  window.localStorage.clear();
  useOverlayVisibilityStore.setState({ ...DEFAULT_OVERLAY_VISIBILITY });
});

function stored(): unknown {
  return JSON.parse(
    window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
  );
}

describe("useOverlayVisibilityStore", () => {
  it("initializes from the persisted (or default) visibility, everything on by default", () => {
    expect(useOverlayVisibilityStore.getState()).toMatchObject(
      DEFAULT_OVERLAY_VISIBILITY,
    );
  });

  it("setAirportsVisible updates state and persists, without touching airspace", () => {
    useOverlayVisibilityStore.getState().setAirportsVisible(false);

    expect(useOverlayVisibilityStore.getState().airports).toBe(false);
    expect(useOverlayVisibilityStore.getState().airspace).toBe(true);
    expect(stored()).toEqual({
      ...DEFAULT_OVERLAY_VISIBILITY,
      airports: false,
    });
  });

  it("setAirspaceVisible updates state and persists, without touching airports", () => {
    useOverlayVisibilityStore.getState().setAirspaceVisible(false);

    expect(useOverlayVisibilityStore.getState().airspace).toBe(false);
    expect(useOverlayVisibilityStore.getState().airports).toBe(true);
    expect(stored()).toEqual({
      ...DEFAULT_OVERLAY_VISIBILITY,
      airspace: false,
    });
  });

  it.each([
    ["setRangeRingsVisible", "rangeRings"],
    ["setReceiverVisible", "receiver"],
    ["setLabelsVisible", "labels"],
  ] as const)("%s updates and persists %s alone", (setter, member) => {
    useOverlayVisibilityStore.getState()[setter](false);

    expect(useOverlayVisibilityStore.getState()[member]).toBe(false);
    expect(stored()).toEqual({
      ...DEFAULT_OVERLAY_VISIBILITY,
      [member]: false,
    });
  });

  it("persists every toggle independently across calls", () => {
    const state = useOverlayVisibilityStore.getState();
    state.setAirportsVisible(false);
    state.setAirspaceVisible(false);
    state.setRangeRingsVisible(false);
    state.setReceiverVisible(false);
    state.setLabelsVisible(false);
    state.setReceiverVisible(true);

    const expected = {
      airports: false,
      airspace: false,
      rangeRings: false,
      receiver: true,
      labels: false,
    };
    expect(useOverlayVisibilityStore.getState()).toMatchObject(expected);
    expect(stored()).toEqual(expected);
  });
});
