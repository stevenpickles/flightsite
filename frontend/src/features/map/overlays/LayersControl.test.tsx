import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LayersControl } from "@/features/map/overlays/LayersControl";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { DEFAULT_OVERLAY_VISIBILITY } from "@/features/map/overlayVisibilityPersistence";
import {
  getMapShortcutTargets,
  setMapShortcutTarget,
} from "@/lib/shortcuts/mapShortcutTargets";
import { installOverlaysApiMock } from "@/test/overlaysApiMock";
import { renderWithProviders } from "@/test/test-utils";

afterEach(() => {
  useOverlayVisibilityStore.setState(DEFAULT_OVERLAY_VISIBILITY);
  setMapShortcutTarget("toggleLayersCard", undefined);
  vi.unstubAllGlobals();
});

function renderControl() {
  installOverlaysApiMock();
  return renderWithProviders(<LayersControl />);
}

describe("LayersControl", () => {
  it("starts open, showing both overlay checkboxes", () => {
    renderControl();
    expect(
      screen.getByRole("checkbox", { name: "Airports" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /Airspace/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /layers/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("collapses and re-expands on its own header button", async () => {
    const user = userEvent.setup();
    renderControl();

    const header = screen.getByRole("button", { name: /layers/i });
    await user.click(header);

    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("checkbox", { name: "Airports" }),
    ).not.toBeInTheDocument();

    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("checkbox", { name: "Airports" }),
    ).toBeInTheDocument();
  });

  it("registers toggleLayersCard on mount and unregisters on unmount", () => {
    const { unmount } = renderControl();
    expect(getMapShortcutTargets().toggleLayersCard).toBeInstanceOf(Function);

    act(() => {
      getMapShortcutTargets().toggleLayersCard?.();
    });
    expect(
      screen.queryByRole("checkbox", { name: "Airports" }),
    ).not.toBeInTheDocument();

    unmount();
    expect(getMapShortcutTargets().toggleLayersCard).toBeUndefined();
  });

  it("still toggles the Airports/Airspace checkboxes through the store", async () => {
    const user = userEvent.setup();
    renderControl();

    const airports = screen.getByRole("checkbox", { name: "Airports" });
    expect(airports).toBeChecked();
    await user.click(airports);
    expect(airports).not.toBeChecked();
    expect(useOverlayVisibilityStore.getState().airports).toBe(false);
  });
});
