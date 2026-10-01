import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ShortcutSheet } from "@/components/shell/ShortcutSheet";
import { SHORTCUTS } from "@/lib/shortcuts/registry";
import { useShortcutSheetStore } from "@/lib/shortcuts/useShortcutSheetStore";

afterEach(() => {
  useShortcutSheetStore.setState({ open: false });
});

describe("ShortcutSheet", () => {
  it("renders nothing while closed", () => {
    render(<ShortcutSheet />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("lists exactly the registry's bindings once opened", () => {
    useShortcutSheetStore.setState({ open: true });
    render(<ShortcutSheet />);

    const dialog = screen.getByRole("dialog", { name: /keyboard shortcuts/i });
    expect(dialog).toBeInTheDocument();
    // `keys` uses double spaces around "then" for legibility in the sheet;
    // `textContent` collapses nothing, so it is compared as-is rather than
    // through `getByText`'s whitespace-normalizing query.
    const dialogText = dialog.textContent ?? "";
    for (const shortcut of SHORTCUTS) {
      expect(screen.getByText(shortcut.description)).toBeInTheDocument();
      expect(dialogText).toContain(shortcut.keys);
    }
  });

  it("closes on the close button", async () => {
    const user = userEvent.setup();
    useShortcutSheetStore.setState({ open: true });
    render(<ShortcutSheet />);

    await user.click(
      screen.getByRole("button", { name: /close keyboard shortcuts/i }),
    );
    expect(useShortcutSheetStore.getState().open).toBe(false);
  });

  it("closes on Escape without letting it reach anything behind it", async () => {
    const user = userEvent.setup();
    useShortcutSheetStore.setState({ open: true });
    render(<ShortcutSheet />);

    const outsideHandler = vitestKeydownSpy();
    await user.keyboard("{Escape}");

    expect(useShortcutSheetStore.getState().open).toBe(false);
    expect(outsideHandler.calls).toBe(0);
    outsideHandler.cleanup();
  });

  it("closes on a click outside the panel", async () => {
    const user = userEvent.setup();
    useShortcutSheetStore.setState({ open: true });
    render(<ShortcutSheet />);

    // The scrim behind the panel — clicking it, not the panel itself.
    await user.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(useShortcutSheetStore.getState().open).toBe(false);
  });
});

/** A `window`-level keydown counter, standing in for
 * `AircraftDetailPanel`'s own Escape handler — proof that the sheet's
 * Escape handling never reaches a listener behind it (see the component's
 * own doc comment on why `onKeyDown` + `stopPropagation` is used instead of
 * a second `window` listener). */
function vitestKeydownSpy() {
  let calls = 0;
  function handler() {
    calls += 1;
  }
  window.addEventListener("keydown", handler);
  return {
    get calls() {
      return calls;
    },
    cleanup: () => window.removeEventListener("keydown", handler),
  };
}
