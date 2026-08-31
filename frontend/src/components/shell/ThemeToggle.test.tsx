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
      screen.getByRole("button", { name: /toggle theme/i }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("flips the theme on click and applies it to the document", async () => {
    const user = userEvent.setup();
    const { ThemeToggle } = await import("./ThemeToggle");
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: /toggle theme/i }));

    expect(screen.getByText("Light theme")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
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
    expect(
      screen.getByRole("button", { name: /toggle theme/i }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("renders icon-only, without dropping the accessible name, when collapsed", async () => {
    const { ThemeToggle } = await import("./ThemeToggle");
    render(<ThemeToggle collapsed />);

    expect(screen.queryByText("Dark theme")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /toggle theme/i }),
    ).toBeInTheDocument();
  });
});
