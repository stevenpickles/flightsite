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

describe("useOverlayVisibilityStore", () => {
  it("initializes from the persisted (or default) visibility, both layers on by default", () => {
    expect(useOverlayVisibilityStore.getState().airports).toBe(true);
    expect(useOverlayVisibilityStore.getState().airspace).toBe(true);
  });

  it("setAirportsVisible updates state and persists, without touching airspace", () => {
    useOverlayVisibilityStore.getState().setAirportsVisible(false);

    expect(useOverlayVisibilityStore.getState().airports).toBe(false);
    expect(useOverlayVisibilityStore.getState().airspace).toBe(true);
    expect(
      JSON.parse(
        window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
      ),
    ).toEqual({ airports: false, airspace: true });
  });

  it("setAirspaceVisible updates state and persists, without touching airports", () => {
    useOverlayVisibilityStore.getState().setAirspaceVisible(false);

    expect(useOverlayVisibilityStore.getState().airspace).toBe(false);
    expect(useOverlayVisibilityStore.getState().airports).toBe(true);
    expect(
      JSON.parse(
        window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
      ),
    ).toEqual({ airports: true, airspace: false });
  });

  it("persists both toggles independently across calls", () => {
    useOverlayVisibilityStore.getState().setAirportsVisible(false);
    useOverlayVisibilityStore.getState().setAirspaceVisible(false);

    expect(useOverlayVisibilityStore.getState()).toMatchObject({
      airports: false,
      airspace: false,
    });
    expect(
      JSON.parse(
        window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
      ),
    ).toEqual({ airports: false, airspace: false });
  });
});
