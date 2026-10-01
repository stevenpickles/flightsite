import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "flightsite-ui-theme";

describe("ThemeToggle", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
  });

  afterEach(() => {
    cleanup();
  });

  it("defaults to the dark theme with no stored preference", async () => {
    const { ThemeToggle } = await import("./ThemeToggle");
    render(<ThemeToggle />);

    expect(screen.getByText("Dark theme")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /toggle theme \(currently dark/i }),
    ).toBeInTheDocument();
  });

  it("cycles Dark -> Light -> System -> Dark on click, applying each to the document", async () => {
    const user = userEvent.setup();
    const { ThemeToggle } = await import("./ThemeToggle");
    render(<ThemeToggle />);

    const button = screen.getByRole("button", { name: /toggle theme/i });

    await user.click(button);
    expect(screen.getByText("Light theme")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");

    await user.click(button);
    expect(screen.getByText("System theme")).toBeInTheDocument();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("system");

    await user.click(button);
    expect(screen.getByText("Dark theme")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("dark");
  });

  it("persists the choice across a simulated reload", async () => {
    const user = userEvent.setup();
    const first = await import("./ThemeToggle");
    const { unmount } = render(<first.ThemeToggle />);

    await user.click(screen.getByRole("button", { name: /toggle theme/i }));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    unmount();

    // Simulate reloading the page: fresh module graph, same localStorage —
    // mirrors what index.html's inline init script + the store do on load.
    vi.resetModules();
    const second = await import("./ThemeToggle");
    render(<second.ThemeToggle />);

    expect(screen.getByText("Light theme")).toBeInTheDocument();
  });

  it("renders icon-only, without dropping the accessible name, when collapsed", async () => {
    const { ThemeToggle } = await import("./ThemeToggle");
    render(<ThemeToggle collapsed />);

    expect(screen.queryByText("Dark theme")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /toggle theme \(currently dark/i }),
    ).toBeInTheDocument();
  });
});
