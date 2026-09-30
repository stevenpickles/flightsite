/**
 * `useKeyboardShortcuts` is only ever mounted via `AppShell`, so it is
 * exercised through `renderApp` rather than in isolation — this is the same
 * approach `Sidebar.test.tsx` and `AppShell.test.tsx` already take for
 * shell-level behaviour.
 */
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useMeasureStore } from "@/features/map/measure/useMeasureStore";
import { DEFAULT_OVERLAY_VISIBILITY } from "@/features/map/overlayVisibilityPersistence";
import { useMapCenterRequestStore } from "@/features/map/store/useMapCenterRequestStore";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { useOverheadStore } from "@/features/overhead/useOverheadStore";
import type { LiveAircraft } from "@/lib/api/live";
import { setMapShortcutTarget } from "@/lib/shortcuts/mapShortcutTargets";
import { useShortcutSheetStore } from "@/lib/shortcuts/useShortcutSheetStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import { getLastMockMap, resetMapLibreMock } from "@/test/maplibreGlMock";
import { installOverlaysApiMock } from "@/test/overlaysApiMock";
import { renderApp } from "@/test/test-utils";

beforeEach(() => {
  resetMapLibreMock();
  installOverlaysApiMock();
});

afterEach(() => {
  useShortcutSheetStore.setState({ open: false });
  setMapShortcutTarget("toggleLayersCard", undefined);
  setMapShortcutTarget("toggleFilterDrawer", undefined);
  setMapShortcutTarget("focusLiveSearch", undefined);
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  useMapCenterRequestStore.setState({ nonce: 0 });
  useMeasureStore.getState().exit();
  useOverheadStore.setState({ open: false });
  window.localStorage.clear();
  useOverlayVisibilityStore.setState({ ...DEFAULT_OVERLAY_VISIBILITY });
  resetFilteredLiveAircraftCache();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Dispatches a `keydown` on `window` — where the dispatcher's listener
 * lives — with `target` left as `window` itself, which `isTypingTarget`
 * correctly treats as "not typing" (it is not an `HTMLElement`). */
function pressKey(key: string, options: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(window, { key, ...options });
}

function seedInterestingAircraft() {
  const aircraft: LiveAircraft[] = [
    makeAircraft({
      icao: "aaaaaa",
      distance_nm: 4,
      interesting: { severity: "high", reasons: ["Rule: Military aircraft"] },
    }),
    makeAircraft({
      icao: "bbbbbb",
      distance_nm: 18,
      interesting: {
        severity: "critical",
        reasons: ["Emergency squawk 7700 (general emergency)"],
      },
    }),
  ];
  act(() => {
    useLiveAircraftStore
      .getState()
      .applySnapshot({ aircraft, receiver: null }, Date.now());
  });
}

describe("useKeyboardShortcuts", () => {
  it("opens the shortcut sheet on '?'", () => {
    renderApp();
    pressKey("?");
    expect(
      screen.getByRole("dialog", { name: /keyboard shortcuts/i }),
    ).toBeInTheDocument();
  });

  it("navigates with a g-sequence (g then m goes to the Live Map)", async () => {
    renderApp("/aircraft");
    await screen.findByRole("heading", { level: 1, name: "Aircraft" });

    pressKey("g");
    pressKey("m");

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 1, name: "Live Map" }),
      ).toBeInTheDocument();
    });
  });

  it("navigates for a second documented g-sequence letter (g then h goes to Health)", async () => {
    renderApp("/");
    pressKey("g");
    pressKey("h");

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 1, name: "Health" }),
      ).toBeInTheDocument();
    });
  });

  it("expires a pending g after the timeout, so a later letter does not navigate", () => {
    vi.useFakeTimers();
    renderApp("/aircraft");

    pressKey("g");
    vi.advanceTimersByTime(1501);
    pressKey("m");

    expect(
      screen.getByRole("heading", { level: 1, name: "Aircraft" }),
    ).toBeInTheDocument();
  });

  it("ignores a Ctrl-held 'g' — no sequence starts", () => {
    renderApp("/aircraft");

    pressKey("g", { ctrlKey: true });
    pressKey("m");

    expect(
      screen.getByRole("heading", { level: 1, name: "Aircraft" }),
    ).toBeInTheDocument();
  });

  it("ignores a Meta- or Alt-held single-letter shortcut on the Live Map", () => {
    const toggleLayers = vi.fn();
    setMapShortcutTarget("toggleLayersCard", toggleLayers);
    renderApp("/");

    pressKey("l", { metaKey: true });
    pressKey("l", { altKey: true });

    expect(toggleLayers).not.toHaveBeenCalled();
  });

  it("suspends every shortcut while focus is in a text field", () => {
    renderApp();
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    // Dispatched on the focused input itself, not `window` directly, so it
    // bubbles with `event.target` set to the input — exactly how a real
    // keypress while typing would arrive.
    fireEvent.keyDown(input, { key: "?" });

    expect(
      screen.queryByRole("dialog", { name: /keyboard shortcuts/i }),
    ).not.toBeInTheDocument();
    document.body.removeChild(input);
  });

  it("dispatches map-only shortcuts only on the Live Map route", async () => {
    // Driven through the real, mounted `LayersControl` — not a spy — since
    // its own registration effect (mount-only, `[]` deps) would otherwise
    // overwrite a pre-set spy the instant the Live Map actually mounts.
    const offMap = renderApp("/aircraft");
    expect(
      screen.queryByRole("button", { name: /layers/i }),
    ).not.toBeInTheDocument();
    offMap.unmount();

    renderApp("/");
    const layersHeader = await screen.findByRole("button", { name: /layers/i });
    expect(layersHeader).toHaveAttribute("aria-expanded", "true");

    pressKey("l");
    expect(layersHeader).toHaveAttribute("aria-expanded", "false");
  });

  it("dispatches the filter-drawer toggle and live-search focus targets on the Live Map", async () => {
    renderApp("/");
    expect(screen.queryByTestId("filter-drawer")).not.toBeInTheDocument();

    pressKey("f");
    expect(await screen.findByTestId("filter-drawer")).toBeInTheDocument();

    pressKey("f");
    expect(screen.queryByTestId("filter-drawer")).not.toBeInTheDocument();

    pressKey("/");
    const search = await screen.findByLabelText(
      /callsign, registration, or icao/i,
    );
    expect(search).toHaveFocus();
  });

  it("steps the selection through the interesting aircraft with '[' and ']'", () => {
    renderApp("/");
    seedInterestingAircraft();

    // Severity descending puts "bbbbbb" (critical) before "aaaaaa" (high) —
    // see `features/interesting/lib/ordering.ts`.
    pressKey("]");
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("bbbbbb");

    pressKey("]");
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");

    pressKey("[");
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("bbbbbb");
  });

  it("recentres the real Live Map on 'H', end to end through RecenterButton", async () => {
    renderApp("/");
    // `MapLibreMap` sets the map instance into context synchronously in its
    // mount effect (see its own doc comment) — no need to wait for `load`.
    const map = getLastMockMap();

    await act(async () => {
      pressKey("h");
    });

    expect(map.easeTo).toHaveBeenCalledTimes(1);
  });

  it("does not recentre or step selection off the Live Map", () => {
    renderApp("/aircraft");
    seedInterestingAircraft();

    pressKey("]");
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
  });

  it("toggles the measure tool on 'M', end to end through MeasureControl", async () => {
    renderApp("/");
    const button = await screen.findByRole("button", {
      name: "Measure distance and bearing",
    });
    expect(button).toHaveAttribute("aria-pressed", "false");

    act(() => {
      pressKey("m");
    });
    expect(useMeasureStore.getState().active).toBe(true);
    expect(button).toHaveAttribute("aria-pressed", "true");

    act(() => {
      pressKey("M", { shiftKey: true });
    });
    expect(useMeasureStore.getState().active).toBe(false);
  });

  it("toggles trails on 'T' and persists the choice", async () => {
    renderApp("/");
    await screen.findByRole("checkbox", { name: "Trails" });

    act(() => {
      pressKey("t");
    });
    expect(useOverlayVisibilityStore.getState().trails).toBe(true);
    expect(screen.getByRole("checkbox", { name: "Trails" })).toBeChecked();

    act(() => {
      pressKey("t");
    });
    expect(useOverlayVisibilityStore.getState().trails).toBe(false);
  });

  it("reads 'g' then 'm' as navigation, never as the measure shortcut", async () => {
    renderApp("/");
    pressKey("g");
    pressKey("m");
    expect(useMeasureStore.getState().active).toBe(false);
  });

  it("dispatches neither 'M' nor 'T' off the Live Map, or while typing", async () => {
    renderApp("/aircraft");
    pressKey("m");
    pressKey("t");
    expect(useMeasureStore.getState().active).toBe(false);
    expect(useOverlayVisibilityStore.getState().trails).toBe(false);
  });

  it("does not dispatch 'W' off the Live Map", async () => {
    renderApp("/aircraft");
    pressKey("w");
    expect(useOverheadStore.getState().open).toBe(false);
  });

  it("suspends 'W' while focus is in a text field on the Live Map", async () => {
    renderApp("/");
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: "w" });
    input.remove();
    expect(useOverheadStore.getState().open).toBe(false);
  });

  it("opens the dialog from 'W' on the Live Map", async () => {
    renderApp("/");
    act(() => {
      pressKey("W");
    });
    expect(useOverheadStore.getState().open).toBe(true);
    expect(
      await screen.findByRole("dialog", { name: "What was that?" }),
    ).toBeInTheDocument();
  });

  it("suspends 'M' and 'T' while focus is in a text field on the Live Map", async () => {
    renderApp("/");
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: "m" });
    fireEvent.keyDown(input, { key: "t" });
    input.remove();
    expect(useMeasureStore.getState().active).toBe(false);
    expect(useOverlayVisibilityStore.getState().trails).toBe(false);
  });
});
