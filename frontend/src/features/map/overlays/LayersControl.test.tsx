import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LayersControl } from "@/features/map/overlays/LayersControl";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import {
  DEFAULT_OVERLAY_VISIBILITY,
  OVERLAY_VISIBILITY_STORAGE_KEY,
} from "@/features/map/overlayVisibilityPersistence";
import {
  getMapShortcutTargets,
  setMapShortcutTarget,
} from "@/lib/shortcuts/mapShortcutTargets";
import { installOverlaysApiMock } from "@/test/overlaysApiMock";
import { renderWithProviders } from "@/test/test-utils";

afterEach(() => {
  window.localStorage.clear();
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

  describe.each(["floating", "docked"] as const)(
    "slice 085 display toggles (%s placement)",
    (placement) => {
      it.each([
        ["Range rings", "rangeRings"],
        ["Receiver", "receiver"],
        ["Labels", "labels"],
      ] as const)(
        "toggles %s through the store and persists it",
        async (name, member) => {
          const user = userEvent.setup();
          installOverlaysApiMock();
          renderWithProviders(<LayersControl placement={placement} />);

          const checkbox = screen.getByRole("checkbox", { name });
          expect(checkbox).toBeChecked();
          await user.click(checkbox);

          expect(checkbox).not.toBeChecked();
          expect(useOverlayVisibilityStore.getState()[member]).toBe(false);
          expect(
            JSON.parse(
              window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ??
                "{}",
            ),
          ).toMatchObject({ [member]: false });

          await user.click(checkbox);
          expect(useOverlayVisibilityStore.getState()[member]).toBe(true);
        },
      );

      it("reflects a stored choice on first render", () => {
        useOverlayVisibilityStore.setState({
          rangeRings: false,
          receiver: true,
          labels: false,
        });
        installOverlaysApiMock();
        renderWithProviders(<LayersControl placement={placement} />);

        expect(
          screen.getByRole("checkbox", { name: "Range rings" }),
        ).not.toBeChecked();
        expect(
          screen.getByRole("checkbox", { name: "Receiver" }),
        ).toBeChecked();
        expect(
          screen.getByRole("checkbox", { name: "Labels" }),
        ).not.toBeChecked();
      });

      it("offers the three label presets, Full checked by default", () => {
        installOverlaysApiMock();
        renderWithProviders(<LayersControl placement={placement} />);

        const group = screen.getByRole("group", { name: "Label content" });
        const radios = within(group).getAllByRole("radio");
        expect(radios.map((radio) => radio.getAttribute("value"))).toEqual([
          "full",
          "compact",
          "altitude",
        ]);
        expect(
          within(group).getByRole("radio", { name: "Full" }),
        ).toBeChecked();
      });

      it("chooses a label preset through the store and persists it", async () => {
        const user = userEvent.setup();
        installOverlaysApiMock();
        renderWithProviders(<LayersControl placement={placement} />);

        await user.click(screen.getByRole("radio", { name: "Altitude only" }));

        expect(useOverlayVisibilityStore.getState().labelPreset).toBe(
          "altitude",
        );
        expect(
          screen.getByRole("radio", { name: "Altitude only" }),
        ).toBeChecked();
        expect(screen.getByRole("radio", { name: "Full" })).not.toBeChecked();
        expect(
          JSON.parse(
            window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
          ),
        ).toMatchObject({ labelPreset: "altitude" });
      });
    },
  );
});
