import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShareControls } from "./ShareControls";

const URL = "https://flightsite.local/aircraft/ae1463";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/**
 * Clipboard interactions use `fireEvent.click`, deliberately not
 * `userEvent.click`: `userEvent.setup()` unconditionally installs its own
 * `navigator.clipboard` stub (`attachClipboardStubToView`, part of its
 * built-in copy/paste support) that overwrites whatever this suite stubs —
 * silently making every copy "succeed" regardless of the scenario a test is
 * trying to set up. `fireEvent` never touches the clipboard machinery, so
 * this suite's own stub is the only one in play.
 */
describe("ShareControls", () => {
  it("copies the link and announces success", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    render(<ShareControls url={URL} title="RCH471" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    });

    expect(writeText).toHaveBeenCalledWith(URL);
    expect(screen.getByRole("status")).toHaveTextContent("Link copied");
  });

  it("resets the announcement after the timeout", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });

    render(<ShareControls url={URL} title="RCH471" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
      // Lets the `copyToClipboard` promise settle (a microtask, unaffected
      // by fake timers) before the assertion below.
      await Promise.resolve();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Link copied");

    act(() => {
      vi.advanceTimersByTime(2001);
    });
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("announces failure without throwing when every copy path fails", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    document.execCommand = vi.fn().mockReturnValue(false);

    render(<ShareControls url={URL} title="RCH471" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      /could not copy the link/i,
    );
  });

  it("shows a Share button only when navigator.share exists", () => {
    vi.stubGlobal("navigator", { ...navigator, share: undefined });
    const { rerender } = render(<ShareControls url={URL} title="RCH471" />);
    expect(
      screen.queryByRole("button", { name: /^share$/i }),
    ).not.toBeInTheDocument();

    vi.stubGlobal("navigator", {
      ...navigator,
      share: vi.fn().mockResolvedValue(undefined),
    });
    rerender(<ShareControls url={URL} title="RCH471" />);
    expect(
      screen.getByRole("button", { name: /^share$/i }),
    ).toBeInTheDocument();
  });

  it("calls navigator.share with the title and url", () => {
    const share = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, share });

    render(<ShareControls url={URL} title="RCH471" />);
    fireEvent.click(screen.getByRole("button", { name: /^share$/i }));

    expect(share).toHaveBeenCalledWith({ title: "RCH471", url: URL });
  });

  it("opens a QR popover encoding the current URL, closable via its own button", async () => {
    const user = userEvent.setup();
    render(<ShareControls url={URL} title="RCH471" />);

    const qrButton = screen.getByRole("button", { name: /qr code/i });
    await user.click(qrButton);

    const popover = screen.getByRole("dialog", { name: /qr code for rch471/i });
    expect(popover.querySelector("svg")).toHaveAttribute(
      "aria-label",
      `QR code encoding ${URL}`,
    );

    await user.click(screen.getByRole("button", { name: /^close$/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes the QR popover on Escape without a window-level listener catching it", async () => {
    const user = userEvent.setup();
    let outsideCalls = 0;
    const handler = () => {
      outsideCalls += 1;
    };
    window.addEventListener("keydown", handler);

    render(<ShareControls url={URL} title="RCH471" />);
    await user.click(screen.getByRole("button", { name: /qr code/i }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(outsideCalls).toBe(0);
    window.removeEventListener("keydown", handler);
  });
});
