/**
 * The aircraft detail panel as the phone Live Map's draggable bottom sheet
 * (`placement="docked"`, roadmap slice 084): snap points, the keyboard
 * Expand/Collapse buttons, pointer drags and taps on the grabber, and that
 * Escape still deselects.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AircraftDetailPanel } from "@/features/aircraft-detail/AircraftDetailPanel";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
});

afterEach(() => {
  useLiveAircraftStore.getState().reset();
  vi.restoreAllMocks();
});

function renderSelectedSheet() {
  render(
    <MemoryRouter>
      <div data-testid="dock">
        <AircraftDetailPanel placement="docked" />
      </div>
    </MemoryRouter>,
  );
  act(() => {
    useLiveAircraftStore.getState().applySnapshot({
      aircraft: [makeAircraft({ icao: "aaaaaa", callsign: "RCH471" })],
      receiver: null,
    });
    useLiveAircraftStore.getState().selectAircraft("aaaaaa");
  });
  return screen.getByTestId("aircraft-detail-panel");
}

/** jsdom lays nothing out, so the heights a drag measures are stubbed: a
 * 700 px dock holding a sheet currently `sheetPx` tall. */
function stubLayout(sheetPx: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      const height =
        this.dataset.testid === "dock"
          ? 700
          : this.dataset.testid === "aircraft-detail-panel"
            ? sheetPx
            : 0;
      return { height, width: 0, top: 0, left: 0 } as DOMRect;
    },
  );
}

describe("AircraftDetailPanel as a phone bottom sheet", () => {
  it("opens at half height inside its container, not fixed to the viewport", () => {
    const sheet = renderSelectedSheet();
    expect(sheet).toHaveAttribute("data-snap", "half");
    expect(sheet.className).toContain("h-1/2");
    expect(sheet.className).not.toContain("fixed");
  });

  it("steps through the snaps with the Expand and Collapse buttons", async () => {
    const user = userEvent.setup();
    const sheet = renderSelectedSheet();
    const expand = screen.getByRole("button", {
      name: "Expand aircraft detail",
    });
    const collapse = screen.getByRole("button", {
      name: "Collapse aircraft detail",
    });

    await user.click(expand);
    expect(sheet).toHaveAttribute("data-snap", "full");
    expect(expand).toBeDisabled();

    await user.click(collapse);
    await user.click(collapse);
    expect(sheet).toHaveAttribute("data-snap", "peek");
    expect(sheet.className).toContain("h-44");
    expect(collapse).toBeDisabled();
    expect(expand).toBeEnabled();
  });

  it("follows a drag on the grabber and settles on the nearest snap", () => {
    const sheet = renderSelectedSheet();
    stubLayout(350);
    const grabber = screen.getByTestId("bottom-sheet-grabber");

    fireEvent.pointerDown(grabber, { pointerId: 1, clientY: 600 });
    fireEvent.pointerMove(grabber, { pointerId: 1, clientY: 320 });
    // 350 + 280 px dragged up, within the 700 px dock.
    expect(sheet.style.height).toBe("630px");

    fireEvent.pointerUp(grabber, { pointerId: 1, clientY: 320 });
    expect(sheet).toHaveAttribute("data-snap", "full");
    expect(sheet.style.height).toBe("");
  });

  it("collapses to peek when dragged down past half", () => {
    const sheet = renderSelectedSheet();
    stubLayout(350);
    const grabber = screen.getByTestId("bottom-sheet-grabber");

    fireEvent.pointerDown(grabber, { pointerId: 1, clientY: 300 });
    fireEvent.pointerMove(grabber, { pointerId: 1, clientY: 600 });
    // Clamped at peek rather than dragged off the bottom.
    expect(sheet.style.height).toBe("176px");
    fireEvent.pointerUp(grabber, { pointerId: 1, clientY: 600 });
    expect(sheet).toHaveAttribute("data-snap", "peek");
  });

  it("treats a tap on the grabber as one step up", () => {
    const sheet = renderSelectedSheet();
    stubLayout(350);
    const grabber = screen.getByTestId("bottom-sheet-grabber");

    fireEvent.pointerDown(grabber, { pointerId: 1, clientY: 400 });
    fireEvent.pointerUp(grabber, { pointerId: 1, clientY: 402 });
    expect(sheet).toHaveAttribute("data-snap", "full");
  });

  it("keeps its snap when the browser cancels the gesture", () => {
    const sheet = renderSelectedSheet();
    stubLayout(350);
    const grabber = screen.getByTestId("bottom-sheet-grabber");

    fireEvent.pointerDown(grabber, { pointerId: 1, clientY: 600 });
    fireEvent.pointerMove(grabber, { pointerId: 1, clientY: 300 });
    fireEvent.pointerCancel(grabber, { pointerId: 1 });
    expect(sheet).toHaveAttribute("data-snap", "half");
    expect(sheet.style.height).toBe("");
  });

  it("still deselects on Escape", async () => {
    const user = userEvent.setup();
    renderSelectedSheet();
    await user.keyboard("{Escape}");
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
    expect(
      screen.queryByTestId("aircraft-detail-panel"),
    ).not.toBeInTheDocument();
  });
});
