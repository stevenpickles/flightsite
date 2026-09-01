/**
 * Unit coverage for overlay focus management (roadmap slice 048): focus
 * restoration on close for every overlay, and a Tab trap for modal ones.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { useDialogFocus } from "@/lib/a11y/useDialogFocus";

function Overlay({ modal }: { modal: boolean }) {
  const [open, setOpen] = useState(false);
  const panelRef = useDialogFocus<HTMLDivElement>({ open, modal });

  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <button type="button">Outside</button>
      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-modal={modal}
          aria-label="Example"
          tabIndex={-1}
        >
          <button type="button">First</button>
          <button type="button">Last</button>
          <button type="button" onClick={() => setOpen(false)}>
            Close
          </button>
        </div>
      )}
    </div>
  );
}

describe("useDialogFocus", () => {
  it("returns focus to the control that opened the overlay when it closes", async () => {
    const user = userEvent.setup();
    render(<Overlay modal={false} />);

    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // Without restoration the closing button unmounts and focus falls to
    // <body>, stranding a keyboard user at the top of the document.
    expect(opener).toHaveFocus();
  });

  it("restores focus for a non-modal overlay too", async () => {
    const user = userEvent.setup();
    render(<Overlay modal={false} />);

    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(opener).toHaveFocus();
  });

  it("wraps Tab from the last focusable element back to the first in a modal", async () => {
    const user = userEvent.setup();
    render(<Overlay modal />);

    await user.click(screen.getByRole("button", { name: "Open" }));

    const last = screen.getByRole("button", { name: "Close" });
    last.focus();
    expect(last).toHaveFocus();

    await user.tab();

    // Trapped: Tab off the end returns to the first control inside the
    // panel instead of escaping to the page behind.
    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
  });

  it("wraps Shift+Tab from the first focusable element to the last in a modal", async () => {
    const user = userEvent.setup();
    render(<Overlay modal />);

    await user.click(screen.getByRole("button", { name: "Open" }));

    const first = screen.getByRole("button", { name: "First" });
    first.focus();

    await user.tab({ shift: true });

    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("does NOT trap Tab in a non-modal overlay", async () => {
    const user = userEvent.setup();
    render(<Overlay modal={false} />);

    await user.click(screen.getByRole("button", { name: "Open" }));

    const last = screen.getByRole("button", { name: "Close" });
    last.focus();
    await user.tab();

    // A non-modal panel leaves the rest of the page reachable by design —
    // trapping here would be the bug, not the fix.
    expect(last).not.toHaveFocus();
    expect(screen.getByRole("button", { name: "First" })).not.toHaveFocus();
  });
});
