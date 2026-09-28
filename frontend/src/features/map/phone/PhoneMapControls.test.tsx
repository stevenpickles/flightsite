/**
 * The phone Live Map layout (roadmap slice 084, issue #227), rendered
 * through `LiveMapPage` below the `md` breakpoint: the bottom toolbar opens
 * one card at a time, Escape closes it, a selection takes the sheet slot,
 * and the slice-082 keyboard shortcuts open the sheets their cards live in.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { usePhoneMapStore } from "@/features/map/phone/usePhoneMapStore";
import { getMapShortcutTargets } from "@/lib/shortcuts/mapShortcutTargets";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import { resetMapLibreMock } from "@/test/maplibreGlMock";
import { installMatchMedia } from "@/test/matchMediaMock";
import { installOverlaysApiMock } from "@/test/overlaysApiMock";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LiveMapPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  resetMapLibreMock();
  resetFilteredLiveAircraftCache();
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  usePhoneMapStore.setState({ openCard: null });
  installOverlaysApiMock();
});

afterEach(() => {
  window.localStorage.clear();
  useLiveAircraftStore.getState().reset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function toolbar() {
  return screen.getByRole("navigation", { name: "Map panels" });
}

function toolbarButton(name: string) {
  return within(toolbar()).getByRole("button", { name });
}

function sheet(card: string) {
  return screen.getByTestId(`phone-map-sheet-${card}`);
}

function selectAircraft() {
  act(() => {
    useLiveAircraftStore.getState().applySnapshot({
      aircraft: [makeAircraft({ icao: "aaaaaa", callsign: "RCH471" })],
      receiver: null,
    });
    useLiveAircraftStore.getState().selectAircraft("aaaaaa");
  });
}

describe("LiveMapPage below the md breakpoint", () => {
  it("replaces the floating cards with a toolbar, every sheet closed", () => {
    installMatchMedia(true);
    renderPage();

    for (const name of ["Today", "Layers", "Filters", "Aircraft", "Activity"]) {
      expect(toolbarButton(name)).toHaveAttribute("aria-expanded", "false");
    }
    for (const card of ["today", "layers", "filters", "aircraft", "activity"]) {
      expect(sheet(card)).not.toBeVisible();
    }
    // The desktop Filters trigger and the skip link are desktop-only.
    expect(screen.getAllByRole("button", { name: /filters/i })).toHaveLength(1);
    expect(
      screen.queryByRole("link", { name: "Skip aircraft list" }),
    ).not.toBeInTheDocument();
    // What stays on the map itself: the connection chip and quick filters.
    expect(screen.getByText("Connecting")).toBeVisible();
    expect(
      screen.getByRole("group", { name: "Quick filters" }),
    ).toBeInTheDocument();
  });

  it("opens one card at a time", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderPage();

    await user.click(toolbarButton("Today"));
    expect(toolbarButton("Today")).toHaveAttribute("aria-expanded", "true");
    expect(sheet("today")).toBeVisible();
    expect(
      within(sheet("today")).getByTestId("today-panel"),
    ).toBeInTheDocument();

    await user.click(toolbarButton("Layers"));
    expect(toolbarButton("Today")).toHaveAttribute("aria-expanded", "false");
    expect(sheet("today")).not.toBeVisible();
    expect(sheet("layers")).toBeVisible();
    expect(
      within(sheet("layers")).getByRole("radiogroup", { name: "Basemap" }),
    ).toBeInTheDocument();
    expect(
      within(sheet("layers")).getByRole("group", { name: "Map layers" }),
    ).toBeInTheDocument();

    // A second tap on the open card's button closes it.
    await user.click(toolbarButton("Layers"));
    expect(sheet("layers")).not.toBeVisible();
    expect(usePhoneMapStore.getState().openCard).toBeNull();
  });

  it("points each toolbar button at the sheet it opens", () => {
    installMatchMedia(true);
    renderPage();
    expect(toolbarButton("Activity")).toHaveAttribute(
      "aria-controls",
      "phone-map-sheet-activity",
    );
    expect(sheet("activity")).toHaveAttribute("id", "phone-map-sheet-activity");
  });

  it("opens the filter form in its sheet and badges active filters", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderPage();

    await user.click(toolbarButton("Filters"));
    expect(
      within(sheet("filters")).getByRole("dialog", {
        name: "Live map filters",
      }),
    ).toBeInTheDocument();

    act(() => {
      useFilterStore.getState().setEmergencyOnly(true);
    });
    expect(screen.getByTestId("phone-filter-active-count")).toHaveTextContent(
      "1",
    );

    await user.click(screen.getByRole("button", { name: "Close filters" }));
    expect(usePhoneMapStore.getState().openCard).toBeNull();
  });

  it("closes an open card on Escape", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderPage();

    await user.click(toolbarButton("Activity"));
    expect(sheet("activity")).toBeVisible();
    await user.keyboard("{Escape}");
    expect(sheet("activity")).not.toBeVisible();
  });

  it("gives the sheet slot to a new selection, and back to a card on request", async () => {
    installMatchMedia(true);
    const user = userEvent.setup();
    renderPage();

    await user.click(toolbarButton("Aircraft"));
    selectAircraft();
    expect(usePhoneMapStore.getState().openCard).toBeNull();
    const detail = screen.getByTestId("aircraft-detail-panel");
    expect(detail).toHaveAttribute("data-snap", "half");
    expect(screen.getByTestId("phone-map-dock")).toContainElement(detail);

    // Opening a card hides the detail sheet without deselecting.
    await user.click(toolbarButton("Today"));
    expect(
      screen.queryByTestId("aircraft-detail-panel"),
    ).not.toBeInTheDocument();
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");

    // Escape closes the card first, bringing the aircraft back...
    await user.keyboard("{Escape}");
    expect(screen.getByTestId("aircraft-detail-panel")).toBeInTheDocument();
    // ...and only then deselects, as on desktop.
    await user.keyboard("{Escape}");
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
  });

  it("routes the L, F and / shortcuts to the sheets", async () => {
    installMatchMedia(true);
    renderPage();
    const targets = getMapShortcutTargets();

    act(() => {
      targets.toggleLayersCard?.();
    });
    expect(sheet("layers")).toBeVisible();

    act(() => {
      targets.toggleFilterDrawer?.();
    });
    expect(usePhoneMapStore.getState().openCard).toBe("filters");
    act(() => {
      targets.toggleFilterDrawer?.();
    });
    expect(usePhoneMapStore.getState().openCard).toBeNull();

    act(() => {
      targets.focusLiveSearch?.();
    });
    expect(sheet("filters")).toBeVisible();
    expect(
      screen.getByLabelText("Callsign, registration, or ICAO"),
    ).toHaveFocus();
  });

  it("switches back to the floating cards when the viewport widens", () => {
    const media = installMatchMedia(true);
    renderPage();
    expect(toolbar()).toBeInTheDocument();

    act(() => {
      media.dispatch(false);
    });
    expect(
      screen.queryByRole("navigation", { name: "Map panels" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("today-panel").className).toContain("absolute");
  });
});

describe("LiveMapPage at desktop width", () => {
  it("renders no phone toolbar", () => {
    installMatchMedia(false);
    renderPage();
    expect(
      screen.queryByRole("navigation", { name: "Map panels" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("phone-map-dock")).not.toBeInTheDocument();
  });
});
